"""Tests unitarios de las reglas deterministas del write-gate CRV."""

from __future__ import annotations

import pytest

from judge.gate import rules
from judge.gate.rules import Issue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _codes(issues: list[Issue]) -> set[str]:
    return {i.code for i in issues}


def _fields(issues: list[Issue]) -> set[str]:
    return {i.field for i in issues}


# ---------------------------------------------------------------------------
# crear_solicitud
# ---------------------------------------------------------------------------


_CREAR_SOLICITUD_OK: dict = {
    "convocatoria_id": "CONV-007",
    "solicitante_id": "PER-123",
    "justificacion": "Cumple con los requisitos de experticia técnica solicitados.",
    "equipo_sugerido": ["PER-124", "PER-125"],
}


def test_crear_solicitud_happy_path() -> None:
    issues = rules.check_crear_solicitud(_CREAR_SOLICITUD_OK)
    assert issues == []
    assert not rules.has_fatal(issues)


def test_crear_solicitud_missing_required_convocatoria() -> None:
    args = {**_CREAR_SOLICITUD_OK}
    del args["convocatoria_id"]
    issues = rules.check_crear_solicitud(args)
    assert "E_REQUIRED" in _codes(issues)
    assert "convocatoria_id" in _fields(issues)
    assert rules.has_fatal(issues)


def test_crear_solicitud_wrong_id_format() -> None:
    args = {**_CREAR_SOLICITUD_OK, "solicitante_id": "PER123"}
    issues = rules.check_crear_solicitud(args)
    assert "E_ID_FORMAT" in _codes(issues)
    assert "solicitante_id" in _fields(issues)


def test_crear_solicitud_equipo_sugerido_item_invalid() -> None:
    args = {**_CREAR_SOLICITUD_OK, "equipo_sugerido": ["PER-124", "juan.perez"]}
    issues = rules.check_crear_solicitud(args)
    assert "E_ID_FORMAT" in _codes(issues)
    assert "equipo_sugerido[1]" in _fields(issues)


def test_crear_solicitud_equipo_sugerido_optional_empty_ok() -> None:
    args = {**_CREAR_SOLICITUD_OK, "equipo_sugerido": []}
    issues = rules.check_crear_solicitud(args)
    # equipo_sugerido es opcional -> lista vacía no debe generar issues.
    assert issues == []


def test_crear_solicitud_justificacion_too_short_is_warn() -> None:
    args = {**_CREAR_SOLICITUD_OK, "justificacion": "corta"}
    issues = rules.check_crear_solicitud(args)
    assert "W_TOO_SHORT" in _codes(issues)
    # Warn no debe hacer fatal si el resto está bien.
    assert not rules.has_fatal(issues)


# ---------------------------------------------------------------------------
# asignar_convocatoria
# ---------------------------------------------------------------------------


_ASIGNAR_OK: dict = {
    "convocatoria_id": "CONV-007",
    "directivo_id": "PER-001",
    "equipo_asignado": ["PER-124", "PER-125"],
    "justificacion": (
        "El equipo asignado cubre las áreas de experticia requeridas por la "
        "convocatoria y tiene la dedicación disponible."
    ),
    "solicitudes_consideradas": ["SOL-042"],
}


def test_asignar_happy_path() -> None:
    issues = rules.check_asignar_convocatoria(_ASIGNAR_OK)
    assert issues == []


def test_asignar_equipo_asignado_no_puede_ir_vacio() -> None:
    args = {**_ASIGNAR_OK, "equipo_asignado": []}
    issues = rules.check_asignar_convocatoria(args)
    assert "E_EMPTY_LIST" in _codes(issues)
    assert "equipo_asignado" in _fields(issues)
    assert rules.has_fatal(issues)


def test_asignar_directivo_id_mal_formado() -> None:
    args = {**_ASIGNAR_OK, "directivo_id": "director-1"}
    issues = rules.check_asignar_convocatoria(args)
    assert "E_ID_FORMAT" in _codes(issues)
    assert "directivo_id" in _fields(issues)


def test_asignar_solicitudes_consideradas_formato_sol() -> None:
    args = {**_ASIGNAR_OK, "solicitudes_consideradas": ["PER-999"]}
    issues = rules.check_asignar_convocatoria(args)
    assert "E_ID_FORMAT" in _codes(issues)
    assert "solicitudes_consideradas[0]" in _fields(issues)


def test_asignar_justificacion_larga_pero_valida() -> None:
    args = {
        **_ASIGNAR_OK,
        "justificacion": "El equipo tiene la experticia y dedicación necesarias xx",
    }
    issues = rules.check_asignar_convocatoria(args)
    # Justo >= 30 chars -> no warn.
    assert not any(i.code == "W_TOO_SHORT" for i in issues)


# ---------------------------------------------------------------------------
# escalar
# ---------------------------------------------------------------------------


_ESCALAR_OK: dict = {
    "convocatoria_id": "CONV-010",
    "etapa_alcanzada": "contraste_requisitos",
    "brechas": ["No se encontró personal con experticia en criptografía."],
    "preguntas_juicio_humano": [
        "¿Se puede contratar externamente para esta convocatoria?",
    ],
}


def test_escalar_happy_path() -> None:
    issues = rules.check_escalar(_ESCALAR_OK)
    assert issues == []


def test_escalar_etapa_invalida() -> None:
    args = {**_ESCALAR_OK, "etapa_alcanzada": "fase_final"}
    issues = rules.check_escalar(args)
    assert "E_ENUM" in _codes(issues)
    assert "etapa_alcanzada" in _fields(issues)
    assert rules.has_fatal(issues)


def test_escalar_brechas_vacias_es_fatal() -> None:
    args = {**_ESCALAR_OK, "brechas": []}
    issues = rules.check_escalar(args)
    assert "E_EMPTY_LIST" in _codes(issues)
    assert "brechas" in _fields(issues)


def test_escalar_preguntas_vacias_es_fatal() -> None:
    args = {**_ESCALAR_OK, "preguntas_juicio_humano": []}
    issues = rules.check_escalar(args)
    assert "E_EMPTY_LIST" in _codes(issues)
    assert "preguntas_juicio_humano" in _fields(issues)


def test_escalar_pregunta_muy_corta_es_warn() -> None:
    args = {**_ESCALAR_OK, "preguntas_juicio_humano": ["¿?"]}
    issues = rules.check_escalar(args)
    assert "W_TOO_SHORT" in _codes(issues)
    assert "preguntas_juicio_humano[0]" in _fields(issues)
    assert not rules.has_fatal(issues)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_cubre_las_tres_tools_criticas() -> None:
    assert set(rules.CHECKERS.keys()) == {
        "crear_solicitud",
        "asignar_convocatoria",
        "escalar",
    }


def test_issue_as_dict_serializable() -> None:
    issue = Issue(code="E_REQUIRED", field="x", severity="fatal", message="falta x")
    assert issue.as_dict() == {
        "code": "E_REQUIRED",
        "field": "x",
        "severity": "fatal",
        "message": "falta x",
    }
