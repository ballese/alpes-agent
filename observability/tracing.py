"""Instrumentación con LangSmith (semana 3, laboratorio 9).

LangGraph y LangChain se trazan solos cuando LANGCHAIN_TRACING_V2=true.
Este módulo agrega:
  - `trazable`: decorador para funciones propias del proyecto (usa
    @traceable de LangSmith solo si el tracing está activo, para que el
    código funcione igual sin credenciales configuradas).
  - `tracing_activo`: chequeo usado por el CLI y los tests.
"""

import os
from typing import Callable


def tracing_activo() -> bool:
    return os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true" and bool(
        os.getenv("LANGCHAIN_API_KEY")
    )


def trazable(name: str | None = None) -> Callable:
    """Aplica @traceable de LangSmith si hay tracing configurado; si no, no-op."""

    def decorator(func: Callable) -> Callable:
        if tracing_activo():
            from langsmith import traceable

            return traceable(name=name or func.__name__)(func)
        return func

    return decorator
