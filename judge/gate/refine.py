"""Fase de **Refine** del write-gate CRV.

Un solo LLM call acotado que recibe (tool, args_originales, issues) y devuelve
args reparados. Todo lo que salga mal (timeout, JSON inválido, LLM caído,
Ollama no configurado) hace **fallback silencioso a los args originales**:
el gate degrada a solo-crítica, nunca rompe el flujo del agente principal.

Diseño:

* Llamada HTTP directa a Ollama ``/api/chat`` con ``format=json``,
  ``temperature=0`` y timeout de 5 s. Sin dependencia de langchain-ollama —
  eso evita el modo de fallo del intento previo (kwarg de timeout distinto
  entre versiones).
* El modelo se lee de ``OLLAMA_MODEL_REFINE`` (default ``llama3.2:1b``); la
  base URL de ``OLLAMA_BASE_URL`` (default ``http://host.docker.internal:11434``).
* Prompt intencionalmente cerrado: instrucciones + JSON de entrada + JSON de
  salida. Sin ejemplos few-shot para mantenerlo barato.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from judge.gate.rules import Issue
from observability.tracing import trazable

_LOG = logging.getLogger("judge.gate.refine")

_REFINE_TIMEOUT_S = 5.0
_DEFAULT_MODEL = "llama3.2:1b"
_DEFAULT_BASE_URL = "http://host.docker.internal:11434"


@dataclass(frozen=True)
class RefineResult:
    """Resultado de un intento de refine.

    Attributes:
        args:      args finales a validar (originales si el LLM falló).
        used_llm:  True si el LLM produjo un JSON aceptable y usable.
        reason:    motivo del fallback (vacío si ``used_llm=True``).
    """

    args: dict[str, Any]
    used_llm: bool
    reason: str = ""


_SYSTEM_PROMPT = (
    "Eres un asistente de reparación de payloads JSON para tools de un agente.\n"
    "Recibirás:\n"
    "  - nombre de la tool crítica de escritura,\n"
    "  - los args originales que el agente construyó (JSON),\n"
    "  - una lista de issues detectados por reglas deterministas.\n"
    "\n"
    "Tu tarea es devolver **exclusivamente** un JSON con los args reparados,\n"
    "corrigiendo cada issue cuando sea posible SIN inventar datos:\n"
    "  - Formatos de id: PER-###, CONV-###, SOL-### (### = 3+ dígitos).\n"
    "  - Nunca inventes ids que no aparezcan ya en los args originales.\n"
    "  - Si un campo requerido falta y no puedes derivarlo, déjalo vacío\n"
    '    ("" o []) para que la re-crítica lo bloquee.\n'
    "  - Solo puedes agregar contenido textual (justificaciones, brechas,\n"
    "    preguntas) si el issue es de longitud mínima y el texto original\n"
    "    ya cubre la intención.\n"
    "  - Mantén todos los campos del payload original, incluso los que no\n"
    "    tenían issues.\n"
    "\n"
    "Formato de salida OBLIGATORIO: un único objeto JSON con la clave\n"
    '"args" que contenga el payload reparado. Sin texto adicional, sin\n'
    "markdown, sin explicaciones."
)


def _build_user_prompt(tool: str, args: dict[str, Any], issues: list[Issue]) -> str:
    payload = {
        "tool": tool,
        "args_originales": args,
        "issues": [i.as_dict() for i in issues],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _model_and_url() -> tuple[str, str]:
    model = os.getenv("OLLAMA_MODEL_REFINE", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    base = os.getenv("OLLAMA_BASE_URL", _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
    return model, base.rstrip("/")


def _extract_repaired_args(raw: str) -> dict[str, Any] | None:
    """Parsea la respuesta del LLM. Devuelve None si no cumple el contrato."""
    if not raw or not raw.strip():
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    # Aceptamos dos formas: {"args": {...}} o directamente {...}. Preferimos la
    # primera porque es la que pedimos en el prompt.
    if "args" in obj and isinstance(obj["args"], dict):
        return obj["args"]
    # Si el modelo respondió con los campos al primer nivel y ninguno es "args",
    # asumimos que ese objeto ES el args.
    if "args" not in obj:
        return obj
    return None


@trazable(name="crv_gate.refine", run_type="llm", tags=["crv", "judge", "refine"])
def refine(tool: str, args: dict[str, Any], issues: list[Issue]) -> RefineResult:
    """Intenta reparar ``args`` con un LLM acotado. Fallback silencioso si algo falla.

    No lanza excepciones al caller: siempre devuelve un ``RefineResult`` con
    ``used_llm=False`` cuando el LLM no está disponible o su salida no cumple
    el contrato JSON.
    """
    model, base_url = _model_and_url()

    request_body = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(tool, args, issues)},
        ],
    }

    try:
        with httpx.Client(timeout=_REFINE_TIMEOUT_S) as client:
            resp = client.post(f"{base_url}/api/chat", json=request_body)
    except httpx.TimeoutException:
        _LOG.info(
            "refine timeout tras %.1fs; fallback a args originales", _REFINE_TIMEOUT_S
        )
        return RefineResult(args=args, used_llm=False, reason="timeout")
    except httpx.HTTPError as exc:
        _LOG.info("refine http error (%s); fallback", exc.__class__.__name__)
        return RefineResult(
            args=args, used_llm=False, reason=f"http:{exc.__class__.__name__}"
        )

    if resp.status_code >= 400:
        _LOG.info("refine ollama status %s; fallback", resp.status_code)
        return RefineResult(
            args=args, used_llm=False, reason=f"status:{resp.status_code}"
        )

    try:
        body = resp.json()
        content = body.get("message", {}).get("content", "")
    except (ValueError, AttributeError):
        return RefineResult(args=args, used_llm=False, reason="bad_response_shape")

    repaired = _extract_repaired_args(content)
    if repaired is None:
        _LOG.info("refine JSON no cumple contrato; fallback")
        return RefineResult(args=args, used_llm=False, reason="bad_json")

    return RefineResult(args=repaired, used_llm=True)
