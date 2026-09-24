"""Judge Agent: auditor A2A conducido por rubricas por tool.

Expone dos operaciones logicas:

* `critique(payload)`: el agente principal esta a punto de ejecutar una tool
  critica. El juez revisa `args` contra la seccion `critique` de la rubrica
  correspondiente y responde:

    - `"OK"` si todos los criterios se cumplen.
    - `"REFINE: <razon breve>"` si algun criterio falla.

* `validate(payload)`: el agente principal ya refino los args tras un REFINE
  previo. El juez revisa los args nuevos contra la seccion `validate` de la
  rubrica y responde con la misma gramatica `OK` / `REFINE: ...`.

La determinismo se apoya en:

1. Rubrica declarativa por tool (`judge/rubrics/<tool>.py`) inyectada como
   bullets en el system prompt.
2. `temperature=0` y `format=json` en Ollama.
3. Parser estricto de la respuesta: cualquier cosa que no encaje en
   `^(OK|REFINE:.*)$` provoca fail-open `"OK"` para no bloquear al agente por
   un problema del auditor.

Si la tool no tiene rubrica registrada, el juez tambien responde `OK`
(fail-open) para no bloquear tools de escritura no cubiertas.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

import httpx

from judge.rubrics import RUBRICS
from observability.tracing import trazable

_LOG = logging.getLogger("judge.audit")

Phase = Literal["critique", "validate"]

_AUDIT_TIMEOUT_S = 8.0
_DEFAULT_MODEL = "llama3.2:1b"
_DEFAULT_BASE_URL = "http://host.docker.internal:11434"


def _model_and_url() -> tuple[str, str]:
    model = os.getenv("OLLAMA_MODEL_JUDGE", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    base = os.getenv("OLLAMA_BASE_URL", _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
    return model, base.rstrip("/")


_SYSTEM_TEMPLATE = (
    "Eres el Judge Agent, un auditor deterministico de acciones de otro agente.\n"
    "Tu unico trabajo es evaluar si los `args` que el agente quiere pasarle a la tool\n"
    "`{tool}` cumplen TODOS los siguientes criterios:\n"
    "\n"
    "{criteria}\n"
    "\n"
    "REGLAS DE RESPUESTA (obligatorias):\n"
    "- Si TODOS los criterios se cumplen, responde EXACTAMENTE: `OK`.\n"
    "- Si al menos uno falla, responde EXACTAMENTE: `REFINE: <razon breve en espanol>`.\n"
    "- La razon debe ser una sola frase que mencione el criterio que fallo y (si aplica)\n"
    "  la pista de reparacion. Considera estas pistas de reparacion:\n"
    "{hints}\n"
    "- No agregues markdown, no expliques mas alla de la frase, no listes multiples issues.\n"
    "- No inventes datos: solo evalua lo que recibes en `args`, `user_request` y `user_profile`.\n"
)


def _render_system(tool: str, criteria: list[str], hints: list[str]) -> str:
    bullets = "\n".join(f"- {c}" for c in criteria)
    hint_lines = "\n".join(f"  * {h}" for h in hints) or "  * (sin pistas adicionales)"
    return _SYSTEM_TEMPLATE.format(tool=tool, criteria=bullets, hints=hint_lines)


def _render_user(payload: dict[str, Any]) -> str:
    """Serializa el payload que el agente 1 envia como bloque JSON para el LLM."""
    return json.dumps(
        {
            "tool": payload.get("tool"),
            "args": payload.get("args", {}),
            "user_request": payload.get("user_request", ""),
            "user_profile": payload.get("user_profile"),
        },
        ensure_ascii=False,
        indent=2,
    )


def _sanitize_reply(raw: str) -> str:
    """Fuerza la respuesta al contrato `OK` o `REFINE: <razon>`.

    Cualquier cosa fuera del contrato se degrada a `OK` (fail-open): el juez
    nunca puede bloquear al agente por errores propios de formato.
    """
    if not raw:
        return "OK"
    text = raw.strip().strip("`").strip()
    # A veces qwen/llama devuelven `OK.` o `Ok` o cosas cercanas.
    upper = text.upper()
    if upper.startswith("OK"):
        return "OK"
    if upper.startswith("REFINE"):
        # Normaliza el prefijo pero conserva la razon.
        rest = text.split(":", 1)
        reason = rest[1].strip() if len(rest) > 1 else ""
        # Recorta la razon a una sola frase razonable.
        reason = reason.split("\n", 1)[0].strip()
        if len(reason) > 240:
            reason = reason[:237] + "..."
        return f"REFINE: {reason or 'criterios no cumplidos'}"
    # Ni OK ni REFINE reconocibles: fail-open.
    _LOG.info("audit reply no reconocida (%r); fail-open OK", text[:80])
    return "OK"


@trazable(name="judge.audit", run_type="chain", tags=["judge", "audit"])
def audit(phase: Phase, payload: dict[str, Any]) -> str:
    """Punto de entrada compartido por critique / validate.

    `payload` debe contener al menos `tool`; opcionalmente `args`,
    `user_request`, `user_profile`. Cualquier fallo (rubrica ausente, LLM caido,
    timeout, respuesta invalida) resulta en `"OK"`.
    """
    tool = payload.get("tool", "")
    rubric = RUBRICS.get(tool)
    if rubric is None:
        _LOG.info("audit sin rubrica para tool=%r; fail-open OK", tool)
        return "OK"

    criteria = rubric.critique if phase == "critique" else rubric.validate
    system = _render_system(rubric.tool, criteria, rubric.refine_hints)
    user = _render_user(payload)

    model, base_url = _model_and_url()
    body = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    try:
        with httpx.Client(timeout=_AUDIT_TIMEOUT_S) as client:
            resp = client.post(f"{base_url}/api/chat", json=body)
    except httpx.TimeoutException:
        _LOG.info("audit timeout tras %.1fs; fail-open OK", _AUDIT_TIMEOUT_S)
        return "OK"
    except httpx.HTTPError as exc:
        _LOG.info("audit http error (%s); fail-open OK", exc.__class__.__name__)
        return "OK"

    if resp.status_code >= 400:
        _LOG.info("audit ollama status %s; fail-open OK", resp.status_code)
        return "OK"

    try:
        content = resp.json().get("message", {}).get("content", "")
    except (ValueError, AttributeError):
        _LOG.info("audit respuesta mal formada; fail-open OK")
        return "OK"

    return _sanitize_reply(content)


def critique(payload: dict[str, Any]) -> str:
    """Fase 1: revision antes de ejecutar la tool."""
    return audit("critique", payload)


def validate(payload: dict[str, Any]) -> str:
    """Fase 2: revision despues de que el agente 1 refino los args."""
    return audit("validate", payload)
