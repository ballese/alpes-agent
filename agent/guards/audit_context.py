"""Contexto de auditoria compartido entre el ReAct loop y `@critical_write`.

Los decoradores no reciben el mensaje del usuario ni el perfil autenticado
como argumentos (son parte del razonamiento del agente, no del payload de la
tool). Este modulo expone un `ContextVar` que:

* La CLI (`cli/main.py`) pobla con el `user_request` del turno actual justo
  antes de invocar el grafo.
* El nodo `actuar` del bucle ReAct (`agent/reasoning/react.py`) actualiza el
  perfil cuando `consultar_mi_perfil_local` retorna con exito.
* `@critical_write` lee para armar el payload A2A que envia al juez.

Usar `ContextVar` (no una variable de modulo) preserva aislamiento entre
turnos concurrentes: cada `asyncio.Task` o hilo hereda su propio snapshot.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, TypedDict


class AuditContext(TypedDict):
    user_request: str
    user_profile: dict[str, Any] | None


_EMPTY: AuditContext = {"user_request": "", "user_profile": None}

_audit_ctx: ContextVar[AuditContext] = ContextVar("audit_ctx", default=_EMPTY)


def set_user_request(texto: str) -> None:
    """Registra el mensaje del usuario para el turno actual."""
    actual = _audit_ctx.get()
    _audit_ctx.set(
        {"user_request": texto or "", "user_profile": actual.get("user_profile")}
    )


def set_user_profile(perfil: dict[str, Any] | None) -> None:
    """Registra el perfil autenticado del usuario (o `None` si aun no lo hay)."""
    actual = _audit_ctx.get()
    _audit_ctx.set(
        {"user_request": actual.get("user_request", ""), "user_profile": perfil}
    )


def get_audit_context() -> AuditContext:
    """Devuelve el contexto de auditoria actual (dict con `user_request` y `user_profile`)."""
    return _audit_ctx.get()


def reset() -> None:
    """Limpia el contexto (util para tests)."""
    _audit_ctx.set(_EMPTY)
