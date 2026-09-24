"""Tipo base compartido por todas las rubricas. Vive en un modulo separado para
evitar el ciclo `judge.rubrics.crear_solicitud` -> `judge.rubrics` -> ...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolRubric:
    """Contrato declarativo del juez para una tool critica."""

    tool: str
    critique: list[str]
    refine_hints: list[str]
    validate: list[str]
