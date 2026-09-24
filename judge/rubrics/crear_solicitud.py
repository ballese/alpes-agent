"""Rubrica para la tool `crear_solicitud` (postulacion a una convocatoria)."""

from __future__ import annotations

from judge.rubrics._base import ToolRubric

RUBRIC = ToolRubric(
    tool="crear_solicitud",
    critique=[
        "`convocatoria_id` debe tener el formato `CONV-###` (### = 3 o mas digitos).",
        "`solicitante_id` debe tener el formato `PER-###`.",
        "Si `user_profile` existe, `solicitante_id` debe coincidir con `user_profile.id` (nadie postula por otro).",
        "`justificacion` no puede estar vacia y debe explicar por que el solicitante encaja en la convocatoria.",
        "`justificacion` debe ser coherente con `user_request` (misma convocatoria o intencion).",
        "Cada id en `equipo_sugerido` debe tener el formato `PER-###`.",
    ],
    refine_hints=[
        "Corrige el formato de ids a `CONV-###` o `PER-###` sin inventar numeros nuevos.",
        "Si `solicitante_id` esta vacio y `user_profile.id` esta disponible, usalo.",
        "Si `justificacion` es demasiado corta, expandela con el motivo del `user_request`.",
    ],
    validate=[
        "`convocatoria_id` = `CONV-###`.",
        "`solicitante_id` = `PER-###` y coincide con `user_profile.id` cuando exista.",
        "`justificacion` no vacia y coherente con `user_request`.",
        "Todos los ids en `equipo_sugerido` son `PER-###`.",
    ],
)
