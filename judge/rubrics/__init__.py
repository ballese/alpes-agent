"""Rubricas por tool que gobiernan el comportamiento del Judge Agent.

Cada tool critica del agente principal tiene un archivo aqui con una
`ToolRubric` que declara:

* `critique`: criterios que el juez evalua ANTES de que el agente ejecute la
  tool. Se inyectan como bullets en el prompt del LLM del juez.
* `refine_hints`: pistas que el juez incluye en el motivo del REFINE para que
  el agente 1 sepa como reparar los args.
* `validate`: criterios de la re-evaluacion DESPUES de que el agente 1 refino.
  Normalmente iguales o mas estrictos que `critique`.

El registro `RUBRICS` es la unica dependencia del modulo `judge.audit`: si un
tool no tiene rubrica, el juez responde `OK` (fail-open) para no romper flujos
de escritura no cubiertos por el gate.
"""

from __future__ import annotations

from judge.rubrics._base import ToolRubric
from judge.rubrics import asignar_convocatoria, crear_solicitud, escalar

__all__ = ["ToolRubric", "RUBRICS"]

RUBRICS: dict[str, ToolRubric] = {
    crear_solicitud.RUBRIC.tool: crear_solicitud.RUBRIC,
    asignar_convocatoria.RUBRIC.tool: asignar_convocatoria.RUBRIC,
    escalar.RUBRIC.tool: escalar.RUBRIC,
}
