"""Trazas simples con LangSmith."""

from __future__ import annotations

import os
from functools import wraps
from functools import lru_cache
from typing import Any, Callable
from uuid import uuid4

SECRETOS = ("api_key", "authorization", "clave", "password", "secret", "token")


def _env(*names: str) -> str:
    return next((os.getenv(name, "") for name in names if os.getenv(name)), "")


def _activo(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def langsmith_project() -> str:
    return _env("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT")


def configurar_langsmith() -> None:
    """Acepta variables LANGCHAIN_* y LANGSMITH_* indistintamente."""
    tracing = _env("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING")
    api_key = _env("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
    project = langsmith_project()

    if tracing:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", tracing)
        os.environ.setdefault("LANGSMITH_TRACING", tracing)
    if api_key:
        os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
        os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    if project:
        os.environ.setdefault("LANGCHAIN_PROJECT", project)
        os.environ.setdefault("LANGSMITH_PROJECT", project)


def tracing_activo() -> bool:
    configurar_langsmith()
    tracing = _env("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING")
    api_key = _env("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
    return _activo(tracing) and bool(api_key)


@lru_cache(maxsize=1)
def preparar_langsmith() -> None:
    """Valida credenciales y crea el proyecto, igual que en el tutorial 9."""
    if not tracing_activo() or not langsmith_project():
        return

    from langsmith import Client

    Client().create_project(project_name=langsmith_project(), upsert=True)


def _limpiar(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(s in str(key).lower() for s in SECRETOS) else _limpiar(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_limpiar(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_limpiar(item) for item in value)
    return value


def trazable(
    name: str | None = None,
    *,
    run_type: str = "chain",
    tags: list[str] | None = None,
    process_inputs: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    process_outputs: Callable[[Any], Any] | None = None,
) -> Callable:
    """Decora una operación y le agrega `operation_id` UUID4 en LangSmith."""

    def decorator(func: Callable) -> Callable:
        if not tracing_activo():
            return func

        from langsmith import traceable

        traced = traceable(
            name=name or func.__name__,
            run_type=run_type,
            tags=tags,
            project_name=langsmith_project() or None,
            process_inputs=process_inputs or _limpiar,
            process_outputs=process_outputs or _limpiar,
        )(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            extra = kwargs.pop("langsmith_extra", None) or {}
            metadata = {**extra.get("metadata", {}), "operation_id": str(uuid4())}
            return traced(
                *args,
                langsmith_extra={**extra, "metadata": metadata},
                **kwargs,
            )

        return wrapper

    return decorator
