"""Decorador ``@critical_write`` para tools críticas del agente principal.

Envuelve la función interna de una tool para que, antes de ejecutarse,
consulte el pipeline CRV del judge (``POST /gate``). El comportamiento se
controla con la env var ``JUDGE_GATE_MODE``:

* ``off``       - no se consulta el judge, la tool se ejecuta tal cual.
* ``advisory``  - (default) se consulta el judge. Si ``block``, la tool se
                  ejecuta con args ORIGINALES pero se añade una advertencia al
                  resultado. Si ``refine-passed``, se ejecutan args reparados
                  con una nota informativa.
* ``blocking``  - si el judge responde ``block``, se rechaza la ejecución y
                  se devuelve un dict de error sin llamar a la tool. Si
                  ``refine-passed``, se ejecutan args reparados.

En todos los modos, si el judge está caído o hay timeout, el decorador es
**fail-open**: ejecuta con los args originales sin bloquear al usuario.

Aplicación en ``agent/tools.py``::

    @tool
    @critical_write("crear_solicitud")
    @trazable(name="crear_solicitud", run_type="tool", tags=["api-empresarial"])
    def crear_solicitud(...): ...

El orden importa: ``@critical_write`` debe ir entre ``@tool`` (LangChain lee
la firma) y ``@trazable`` (el trace incluye la llamada al gate como parte del
tiempo de la tool).
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable

from agent.guards.gate_client import call_gate

_LOG = logging.getLogger("agent.guards.critical_write")

_VALID_MODES = frozenset({"off", "advisory", "blocking"})
_DEFAULT_MODE = "advisory"


def _current_mode() -> str:
    raw = os.getenv("JUDGE_GATE_MODE", _DEFAULT_MODE).strip().lower()
    if raw not in _VALID_MODES:
        _LOG.warning("JUDGE_GATE_MODE='%s' inválido; usando '%s'", raw, _DEFAULT_MODE)
        return _DEFAULT_MODE
    return raw


def _issues_summary(issues: list[dict[str, Any]]) -> str:
    """Formato corto de issues para incluir en la respuesta al agente."""
    if not issues:
        return "(sin issues)"
    partes = []
    for issue in issues[:5]:  # cap para no explotar el context
        code = issue.get("code", "?")
        field = issue.get("field", "?")
        msg = issue.get("message", "")
        partes.append(f"[{code}] {field}: {msg}")
    if len(issues) > 5:
        partes.append(f"... (+{len(issues) - 5} más)")
    return " | ".join(partes)


def critical_write(
    tool_name: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Marca una tool como crítica de escritura y la enruta por el CRV gate.

    Args:
        tool_name: nombre lógico de la tool (debe coincidir con la clave
            registrada en ``judge.gate.rules.CHECKERS``).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(**kwargs: Any) -> Any:
            mode = _current_mode()

            # Modo off: bypass total.
            if mode == "off":
                return func(**kwargs)

            gate = call_gate(tool_name, kwargs)

            # Fail-open: judge caído o respuesta inválida -> ejecutamos original.
            if gate is None:
                _LOG.info(
                    "write-gate no disponible para '%s'; ejecutando con args originales",
                    tool_name,
                )
                return func(**kwargs)

            status = gate.get("status")
            args_final = gate.get("args_final", kwargs)
            issues_initial = gate.get("issues_initial", [])
            issues_final = gate.get("issues_final", [])

            if status == "pass":
                return func(**args_final)

            if status == "refine-passed":
                result = func(**args_final)
                # Anotamos la reparación solo si el resultado es un dict serializable.
                if isinstance(result, dict) and "error" not in result:
                    result = {
                        **result,
                        "_gate": {
                            "status": "refine-passed",
                            "note": (
                                "El auditor reparó los argumentos antes de ejecutar la tool."
                            ),
                            "issues_reparados": _issues_summary(issues_initial),
                        },
                    }
                return result

            if status == "block":
                if mode == "blocking":
                    _LOG.info(
                        "write-gate BLOCK (blocking mode) para '%s': %s",
                        tool_name,
                        _issues_summary(issues_final or issues_initial),
                    )
                    return {
                        "error": "blocked_by_gate",
                        "tool": tool_name,
                        "issues": issues_final or issues_initial,
                        "hint": (
                            "El auditor rechazó la acción por args mal formados. "
                            "Revisa los issues y reintenta con datos corregidos."
                        ),
                    }
                # advisory: ejecutamos con args ORIGINALES pero avisamos.
                _LOG.info(
                    "write-gate BLOCK (advisory) para '%s': ejecutando de todos modos con originales",
                    tool_name,
                )
                result = func(**kwargs)
                if isinstance(result, dict) and "error" not in result:
                    result = {
                        **result,
                        "_gate": {
                            "status": "block",
                            "mode": "advisory",
                            "note": (
                                "El auditor detectó problemas pero el modo advisory "
                                "no bloquea la ejecución."
                            ),
                            "issues": _issues_summary(issues_final or issues_initial),
                        },
                    }
                return result

            # Status desconocido: fail-open.
            _LOG.warning("write-gate status desconocido '%s'; fail-open", status)
            return func(**kwargs)

        return wrapper

    return decorator
