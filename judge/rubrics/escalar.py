"""Rubrica para la tool `escalar` (derivar a decision humana)."""

from __future__ import annotations

from judge.rubrics._base import ToolRubric

RUBRIC = ToolRubric(
    tool="escalar",
    critique=[
        "`convocatoria_id` debe tener el formato `CONV-###`.",
        "`etapa_alcanzada` debe ser exactamente una de: "
        "`escaneo_inicial`, `contraste_requisitos`, `conformacion_equipo`.",
        "`brechas` debe ser una lista no vacia con al menos un item textual.",
        "`preguntas_juicio_humano` debe ser una lista no vacia con al menos una pregunta clara.",
        "Las `brechas` y `preguntas_juicio_humano` deben ser coherentes con `user_request` "
        "(no escalar por temas ajenos al pedido del usuario).",
    ],
    refine_hints=[
        "Si `etapa_alcanzada` esta fuera del enum, mapeala al valor mas cercano por semantica.",
        "Si `brechas` o `preguntas_juicio_humano` estan vacias y el `user_request` da contexto,",
        "extrae al menos un item de ese texto.",
    ],
    validate=[
        "`convocatoria_id` = `CONV-###`.",
        "`etapa_alcanzada` in {escaneo_inicial, contraste_requisitos, conformacion_equipo}.",
        "`brechas` y `preguntas_juicio_humano` son listas no vacias.",
        "Contenido coherente con `user_request`.",
    ],
)
