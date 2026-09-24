"""Rubrica para la tool `asignar_convocatoria` (accion exclusiva de directivos)."""

from __future__ import annotations

from judge.rubrics._base import ToolRubric

RUBRIC = ToolRubric(
    tool="asignar_convocatoria",
    critique=[
        "`convocatoria_id` debe tener el formato `CONV-###`.",
        "`directivo_id` debe tener el formato `PER-###`.",
        "Si `user_profile` existe, `user_profile.rol` debe ser exactamente `directivo` "
        "(personal comun NO puede asignar).",
        "Si `user_profile` existe, `directivo_id` debe coincidir con `user_profile.id`.",
        "`equipo_asignado` no puede estar vacio y cada id debe ser `PER-###`.",
        "`justificacion` no puede estar vacia y debe explicar por que ese equipo encaja.",
        "Cada id en `solicitudes_consideradas` debe tener el formato `SOL-###`.",
    ],
    refine_hints=[
        "Si `user_profile.rol` no es `directivo`, la accion es imposible: deja los args tal cual",
        "para que la validacion la bloquee.",
        "Formatea ids como `CONV-###`, `PER-###`, `SOL-###` sin inventar numeros nuevos.",
        "Si `justificacion` es corta, expandela con motivo del `user_request` y el perfil del equipo.",
    ],
    validate=[
        "`user_profile.rol` = `directivo` (si `user_profile` esta presente).",
        "`convocatoria_id` = `CONV-###`, `directivo_id` = `PER-###`.",
        "`equipo_asignado` no vacio y todos `PER-###`.",
        "`justificacion` no vacia y coherente con `user_request`.",
        "Ids en `solicitudes_consideradas` son `SOL-###`.",
    ],
)
