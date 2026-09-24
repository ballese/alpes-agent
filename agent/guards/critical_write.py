"""Decorador `@critical_write` — conversacion A2A con el Judge Agent.

Antes de ejecutar una tool critica, el agente 1 pide al agente 2 (juez):

1. **critique** con los args originales, `user_request` y `user_profile`.
2. Si el juez responde `OK`, la tool se ejecuta tal cual.
3. Si responde `REFINE: <razon>`, el agente 1 usa su propio `ChatOllama` para
   reparar los args con el motivo como pista, y pide **validate** con los args
   nuevos.
4. Si `validate` responde `OK`, la tool se ejecuta con los args refinados.
5. Si `validate` sigue en `REFINE`, se cae al modo configurado (`blocking`
   rechaza; `advisory` ejecuta con args originales y adjunta warning).

Modos (via env var `JUDGE_GATE_MODE`):

* ``off``       - no se consulta al juez, la tool se ejecuta tal cual.
* ``advisory``  - (default) el juez opina pero un veredicto adverso no bloquea.
* ``blocking``  - un veredicto adverso final impide la ejecucion.

Fail-open transversal: cualquier fallo del cliente A2A degrada a `"OK"` para
que el juez nunca sea un punto unico de falla.

Cap de llamadas = 2 (critique + validate). Como maximo una ronda de refine
local: mantiene la latencia total del write-gate acotada en Ollama local.
"""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Callable

from agent.audit_client import ask_critique, ask_validate
from agent.guards.audit_context import get_audit_context
from cli.config import get_settings
from cli.ui import console as _console, design as _design
from observability.tracing import trazable

_LOG = logging.getLogger("agent.guards.critical_write")

_VALID_MODES = frozenset({"off", "advisory", "blocking"})
_DEFAULT_MODE = "advisory"


def _current_mode() -> str:
    raw = os.getenv("JUDGE_GATE_MODE", _DEFAULT_MODE).strip().lower()
    if raw not in _VALID_MODES:
        _LOG.warning("JUDGE_GATE_MODE='%s' invalido; usando '%s'", raw, _DEFAULT_MODE)
        return _DEFAULT_MODE
    return raw


def _print_juez(tool_name: str, status: str, detalle: str = "") -> None:
    """Imprime una linea dim en la CLI con el veredicto del juez.

    Respeta `display.show_tool_calls` en `cli_design.toml`. Envuelto en
    try/except: un fallo de la CLI nunca rompe el flujo del write-gate.
    """
    try:
        d = _design()
        if not d["display"]["show_tool_calls"]:
            return
        color = d["colors"]["dim"]
        cuerpo = f"{status} ({detalle})" if detalle else status
        _console.print(f"  [{color}][juez] {tool_name} -> {cuerpo}[/{color}]")
    except Exception:  # noqa: BLE001
        pass


def _parse_reply(reply: str) -> tuple[bool, str]:
    """Devuelve `(is_ok, reason)`. `is_ok=True` cuando el juez respondio OK."""
    text = (reply or "").strip()
    if text.upper().startswith("OK"):
        return True, ""
    if text.upper().startswith("REFINE"):
        _, _, reason = text.partition(":")
        return False, reason.strip() or "criterios no cumplidos"
    # Cualquier otra cosa: fail-open a OK (el juez ya sanitiza, pero por si acaso).
    return True, ""


_REFINE_SYSTEM = (
    "Eres el asistente del agente principal. Debes REPARAR los args que ibas a "
    "pasarle a una tool critica, siguiendo la razon que el juez devolvio. "
    "Devuelves EXCLUSIVAMENTE un objeto JSON con los args reparados: mismas "
    "claves que los originales (no agregues ni quites campos, salvo si la razon "
    "lo pide explicitamente). No inventes ids: usa los que ya venian en `args` "
    "o en `user_profile`. Si no puedes reparar algo con la informacion "
    "disponible, deja el campo tal cual estaba. No markdown, no explicacion, "
    "solo el JSON."
)


def _refine_args_locally(
    tool_name: str,
    original_args: dict[str, Any],
    reason: str,
    user_request: str,
    user_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """LLM local del agente 1 que repara los args segun el motivo del juez.

    Cualquier fallo (LLM caido, JSON invalido) devuelve los args originales:
    la validacion posterior decidira si bloquear o no.
    """
    try:
        # Import diferido: langchain_ollama es pesado y solo hace falta si
        # realmente entramos en el camino de refine.
        from langchain_ollama import ChatOllama

        settings = get_settings()
        model = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            format="json",
        )
        user = json.dumps(
            {
                "tool": tool_name,
                "args_originales": original_args,
                "motivo_juez": reason,
                "user_request": user_request,
                "user_profile": user_profile,
            },
            ensure_ascii=False,
            indent=2,
        )
        resp = model.invoke(
            [
                {"role": "system", "content": _REFINE_SYSTEM},
                {"role": "user", "content": user},
            ]
        )
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        obj = json.loads(content)
        if isinstance(obj, dict) and "args" in obj and isinstance(obj["args"], dict):
            return obj["args"]
        if isinstance(obj, dict):
            return obj
    except Exception as exc:  # noqa: BLE001
        _LOG.info(
            "refine local fallo (%s); usando args originales", exc.__class__.__name__
        )
    return original_args


def critical_write(
    tool_name: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Marca una tool como critica de escritura y la enruta por la conversacion A2A."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        @trazable(name="critical_write", run_type="chain", tags=["a2a", "write-gate"])
        def wrapper(**kwargs: Any) -> Any:
            mode = _current_mode()
            if mode == "off":
                return func(**kwargs)

            ctx = get_audit_context()
            user_request = ctx.get("user_request", "")
            user_profile = ctx.get("user_profile")

            base_payload: dict[str, Any] = {
                "tool": tool_name,
                "args": dict(kwargs),
                "user_request": user_request,
                "user_profile": user_profile,
            }

            # Fase 1: critique
            critique_reply = ask_critique(base_payload)
            ok, reason = _parse_reply(critique_reply)
            if ok:
                _print_juez(tool_name, "ok")
                return func(**kwargs)

            # Fase 2: refine local + validate
            new_args = _refine_args_locally(
                tool_name, dict(kwargs), reason, user_request, user_profile
            )
            validate_payload = {**base_payload, "args": new_args}
            validate_reply = ask_validate(validate_payload)
            ok2, reason2 = _parse_reply(validate_reply)

            if ok2:
                _print_juez(tool_name, "refinado", reason)
                result = func(**new_args)
                if isinstance(result, dict) and "error" not in result:
                    result = {
                        **result,
                        "_juez": {
                            "status": "refinado",
                            "motivo_critique": reason,
                            "nota": "El juez pidio refinar los args; validate aprobo la nueva version.",
                        },
                    }
                return result

            # Refine no basto: cap alcanzado. Modo decide.
            if mode == "blocking":
                _print_juez(tool_name, "bloqueado", reason2)
                return {
                    "error": "blocked_by_judge",
                    "tool": tool_name,
                    "motivo_critique": reason,
                    "motivo_validate": reason2,
                    "hint": (
                        "El juez rechazo la accion en critique y en validate. "
                        "Revisa los motivos y reintenta con datos corregidos."
                    ),
                }

            # advisory: ejecuta con args ORIGINALES y anota warning.
            _print_juez(tool_name, "warn", reason2)
            result = func(**kwargs)
            if isinstance(result, dict) and "error" not in result:
                result = {
                    **result,
                    "_juez": {
                        "status": "warn",
                        "modo": "advisory",
                        "motivo_critique": reason,
                        "motivo_validate": reason2,
                        "nota": "El juez rechazo la accion pero el modo advisory no bloquea.",
                    },
                }
            return result

        return wrapper

    return decorator
