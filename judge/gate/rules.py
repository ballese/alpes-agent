"""Fase de **Critique** del write-gate CRV.

Reglas deterministas sobre los args de las tres tools críticas de escritura.
Sin I/O, sin LLM, sin dependencias externas: solo forma/estructura del payload.

Contrato de cada checker:

    check_<tool>(args: dict) -> list[Issue]

Devuelve **lista vacía si el payload es correcto**. Cada ``Issue`` tiene una
severidad (``fatal`` bloquea, ``warn`` solo informa) y un mensaje corto.

Estas reglas son intencionalmente conservadoras: preferimos falsos positivos
(el LLM refine puede corregir) sobre falsos negativos (una acción irreversible
que llega mal formada a la API empresarial).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Constantes de formato (alineadas con la API empresarial del curso)
# ---------------------------------------------------------------------------

_ID_PERSONA_RE = re.compile(r"^PER-\d{3,}$")
_ID_CONVOCATORIA_RE = re.compile(r"^CONV-\d{3,}$")
_ID_SOLICITUD_RE = re.compile(r"^SOL-\d{3,}$")

_ETAPAS_ESCALAMIENTO = frozenset(
    {"escaneo_inicial", "contraste_requisitos", "conformacion_equipo"}
)

# Umbrales de longitud mínima (solo warn, no fatal).
_JUSTIF_SOLICITUD_MIN = 20
_JUSTIF_ASIGNACION_MIN = 30
_PREGUNTA_MIN = 10


# ---------------------------------------------------------------------------
# Modelo de Issue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """Un hallazgo estructurado de la fase de crítica.

    Attributes:
        code:     identificador estable (ej. ``E_ID_FORMAT``) para trazas.
        field:    ruta del campo con problema (ej. ``"equipo_asignado[0]"``).
        severity: ``"fatal"`` bloquea la acción; ``"warn"`` solo informa.
        message:  descripción legible, sirve como pista para el refine LLM.
    """

    code: str
    field: str
    severity: str  # "fatal" | "warn"
    message: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers de validación
# ---------------------------------------------------------------------------


def _require_str(args: dict[str, Any], field: str, issues: list[Issue]) -> str | None:
    """Verifica que ``field`` sea un string no vacío. Anota Issue si no lo es."""
    value = args.get(field)
    if value is None or value == "":
        issues.append(
            Issue(
                code="E_REQUIRED",
                field=field,
                severity="fatal",
                message=f"El campo '{field}' es obligatorio.",
            )
        )
        return None
    if not isinstance(value, str):
        issues.append(
            Issue(
                code="E_TYPE",
                field=field,
                severity="fatal",
                message=f"El campo '{field}' debe ser string, no {type(value).__name__}.",
            )
        )
        return None
    return value


def _check_id_format(
    field: str, value: str, pattern: re.Pattern[str], issues: list[Issue]
) -> None:
    if not pattern.match(value):
        issues.append(
            Issue(
                code="E_ID_FORMAT",
                field=field,
                severity="fatal",
                message=(
                    f"'{value}' no cumple el formato esperado para '{field}' "
                    f"(patrón {pattern.pattern})."
                ),
            )
        )


def _check_id_list(
    field: str,
    values: Any,
    pattern: re.Pattern[str],
    issues: list[Issue],
    *,
    require_non_empty: bool,
) -> None:
    if values is None:
        if require_non_empty:
            issues.append(
                Issue(
                    code="E_REQUIRED",
                    field=field,
                    severity="fatal",
                    message=f"El campo '{field}' es obligatorio y no puede ir vacío.",
                )
            )
        return
    if not isinstance(values, list):
        issues.append(
            Issue(
                code="E_TYPE",
                field=field,
                severity="fatal",
                message=f"El campo '{field}' debe ser lista, no {type(values).__name__}.",
            )
        )
        return
    if require_non_empty and len(values) == 0:
        issues.append(
            Issue(
                code="E_EMPTY_LIST",
                field=field,
                severity="fatal",
                message=f"El campo '{field}' no puede estar vacío.",
            )
        )
        return
    for idx, item in enumerate(values):
        subfield = f"{field}[{idx}]"
        if not isinstance(item, str):
            issues.append(
                Issue(
                    code="E_TYPE",
                    field=subfield,
                    severity="fatal",
                    message=f"'{subfield}' debe ser string, no {type(item).__name__}.",
                )
            )
            continue
        _check_id_format(subfield, item, pattern, issues)


def _check_min_length(
    field: str, value: str, minimum: int, issues: list[Issue]
) -> None:
    if len(value.strip()) < minimum:
        issues.append(
            Issue(
                code="W_TOO_SHORT",
                field=field,
                severity="warn",
                message=(
                    f"'{field}' tiene {len(value.strip())} caracteres; "
                    f"se recomienda al menos {minimum} para justificar la acción."
                ),
            )
        )


# ---------------------------------------------------------------------------
# Checkers por tool
# ---------------------------------------------------------------------------


def check_crear_solicitud(args: dict[str, Any]) -> list[Issue]:
    """Crítica de args para ``crear_solicitud`` (POST /solicitudes)."""
    issues: list[Issue] = []

    conv = _require_str(args, "convocatoria_id", issues)
    if conv is not None:
        _check_id_format("convocatoria_id", conv, _ID_CONVOCATORIA_RE, issues)

    sol = _require_str(args, "solicitante_id", issues)
    if sol is not None:
        _check_id_format("solicitante_id", sol, _ID_PERSONA_RE, issues)

    justif = _require_str(args, "justificacion", issues)
    if justif is not None:
        _check_min_length("justificacion", justif, _JUSTIF_SOLICITUD_MIN, issues)

    _check_id_list(
        "equipo_sugerido",
        args.get("equipo_sugerido"),
        _ID_PERSONA_RE,
        issues,
        require_non_empty=False,
    )

    return issues


def check_asignar_convocatoria(args: dict[str, Any]) -> list[Issue]:
    """Crítica de args para ``asignar_convocatoria`` (POST /asignaciones)."""
    issues: list[Issue] = []

    conv = _require_str(args, "convocatoria_id", issues)
    if conv is not None:
        _check_id_format("convocatoria_id", conv, _ID_CONVOCATORIA_RE, issues)

    direct = _require_str(args, "directivo_id", issues)
    if direct is not None:
        _check_id_format("directivo_id", direct, _ID_PERSONA_RE, issues)

    _check_id_list(
        "equipo_asignado",
        args.get("equipo_asignado"),
        _ID_PERSONA_RE,
        issues,
        require_non_empty=True,
    )

    justif = _require_str(args, "justificacion", issues)
    if justif is not None:
        _check_min_length("justificacion", justif, _JUSTIF_ASIGNACION_MIN, issues)

    _check_id_list(
        "solicitudes_consideradas",
        args.get("solicitudes_consideradas"),
        _ID_SOLICITUD_RE,
        issues,
        require_non_empty=False,
    )

    return issues


def check_escalar(args: dict[str, Any]) -> list[Issue]:
    """Crítica de args para ``escalar`` (POST /escalamientos)."""
    issues: list[Issue] = []

    conv = _require_str(args, "convocatoria_id", issues)
    if conv is not None:
        _check_id_format("convocatoria_id", conv, _ID_CONVOCATORIA_RE, issues)

    etapa = _require_str(args, "etapa_alcanzada", issues)
    if etapa is not None and etapa not in _ETAPAS_ESCALAMIENTO:
        issues.append(
            Issue(
                code="E_ENUM",
                field="etapa_alcanzada",
                severity="fatal",
                message=(
                    f"'etapa_alcanzada'='{etapa}' no está en el conjunto permitido: "
                    f"{sorted(_ETAPAS_ESCALAMIENTO)}."
                ),
            )
        )

    brechas = args.get("brechas")
    if brechas is None or (isinstance(brechas, list) and len(brechas) == 0):
        issues.append(
            Issue(
                code="E_EMPTY_LIST",
                field="brechas",
                severity="fatal",
                message="'brechas' debe contener al menos una brecha identificada.",
            )
        )
    elif not isinstance(brechas, list):
        issues.append(
            Issue(
                code="E_TYPE",
                field="brechas",
                severity="fatal",
                message=f"'brechas' debe ser lista, no {type(brechas).__name__}.",
            )
        )

    preguntas = args.get("preguntas_juicio_humano")
    if preguntas is None or (isinstance(preguntas, list) and len(preguntas) == 0):
        issues.append(
            Issue(
                code="E_EMPTY_LIST",
                field="preguntas_juicio_humano",
                severity="fatal",
                message=(
                    "'preguntas_juicio_humano' debe contener al menos una pregunta "
                    "concreta para el equipo humano."
                ),
            )
        )
    elif not isinstance(preguntas, list):
        issues.append(
            Issue(
                code="E_TYPE",
                field="preguntas_juicio_humano",
                severity="fatal",
                message=(
                    f"'preguntas_juicio_humano' debe ser lista, "
                    f"no {type(preguntas).__name__}."
                ),
            )
        )
    else:
        for idx, item in enumerate(preguntas):
            subfield = f"preguntas_juicio_humano[{idx}]"
            if not isinstance(item, str):
                issues.append(
                    Issue(
                        code="E_TYPE",
                        field=subfield,
                        severity="fatal",
                        message=f"'{subfield}' debe ser string.",
                    )
                )
                continue
            _check_min_length(subfield, item, _PREGUNTA_MIN, issues)

    return issues


# ---------------------------------------------------------------------------
# Registry (usado por pipeline y por POST /gate)
# ---------------------------------------------------------------------------


CHECKERS: dict[str, Callable[[dict[str, Any]], list[Issue]]] = {
    "crear_solicitud": check_crear_solicitud,
    "asignar_convocatoria": check_asignar_convocatoria,
    "escalar": check_escalar,
}


def has_fatal(issues: list[Issue]) -> bool:
    """True si al menos un issue es fatal (bloquearía la acción)."""
    return any(i.severity == "fatal" for i in issues)
