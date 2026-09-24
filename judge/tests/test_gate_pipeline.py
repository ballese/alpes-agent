"""Tests de la orquestación Critique -> Refine -> Validate.

El LLM real no se toca aquí: mockeamos ``judge.gate.refine.refine`` para
cubrir los cuatro caminos del pipeline (pass, refine-passed, block por
fallback, block por fatal-after-refine).
"""

from __future__ import annotations

from typing import Any

import pytest

from judge.gate import pipeline
from judge.gate import refine as refine_mod
from judge.gate.pipeline import GateResult, UnknownToolError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_ARGS_OK: dict[str, Any] = {
    "convocatoria_id": "CONV-007",
    "solicitante_id": "PER-123",
    "justificacion": "Cumple con la experticia y la dedicación solicitadas.",
    "equipo_sugerido": ["PER-124"],
}

_ARGS_BAD: dict[str, Any] = {
    # Formato mal en ambos ids -> fatales seguros.
    "convocatoria_id": "conv7",
    "solicitante_id": "juan.perez",
    "justificacion": "Cumple con la experticia y la dedicación solicitadas.",
    "equipo_sugerido": [],
}


class _FakeRefine:
    """Reemplaza ``refine_mod.refine`` con un resultado predecible."""

    def __init__(
        self,
        *,
        used_llm: bool,
        repaired_args: dict[str, Any] | None = None,
        reason: str = "",
    ) -> None:
        self.used_llm = used_llm
        self.repaired_args = repaired_args
        self.reason = reason
        self.calls: list[tuple[str, dict[str, Any], list]] = []

    def __call__(
        self, tool: str, args: dict[str, Any], issues: list
    ) -> refine_mod.RefineResult:
        self.calls.append((tool, args, issues))
        return refine_mod.RefineResult(
            args=self.repaired_args if self.used_llm else args,
            used_llm=self.used_llm,
            reason=self.reason,
        )


# ---------------------------------------------------------------------------
# Camino 1: pass
# ---------------------------------------------------------------------------


def test_pipeline_pass_no_llamada_a_refine(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRefine(used_llm=False, reason="no_deberia_llamarse")
    monkeypatch.setattr(refine_mod, "refine", fake)

    result = pipeline.run_gate("crear_solicitud", _ARGS_OK)

    assert isinstance(result, GateResult)
    assert result.status == "pass"
    assert result.args_final == _ARGS_OK
    assert result.refine_used is False
    assert result.issues_final == []
    # Confirmación clave: no debe invocarse el LLM cuando no hay fatales.
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Camino 2: refine-passed
# ---------------------------------------------------------------------------


def test_pipeline_refine_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    repaired = {**_ARGS_BAD, "convocatoria_id": "CONV-007", "solicitante_id": "PER-123"}
    fake = _FakeRefine(used_llm=True, repaired_args=repaired)
    monkeypatch.setattr(refine_mod, "refine", fake)

    result = pipeline.run_gate("crear_solicitud", _ARGS_BAD)

    assert result.status == "refine-passed"
    assert result.args_final == repaired
    assert result.refine_used is True
    assert result.issues_initial != []  # tenía fatales
    assert result.issues_final == []  # ya limpio
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Camino 3: block por fallback del LLM
# ---------------------------------------------------------------------------


def test_pipeline_block_cuando_llm_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRefine(used_llm=False, reason="timeout")
    monkeypatch.setattr(refine_mod, "refine", fake)

    result = pipeline.run_gate("crear_solicitud", _ARGS_BAD)

    assert result.status == "block"
    assert result.refine_used is False
    assert result.refine_reason == "timeout"
    # args_final debe ser los originales cuando el refine no aportó nada.
    assert result.args_final == _ARGS_BAD


# ---------------------------------------------------------------------------
# Camino 4: block porque el refine reparó pero siguen quedando fatales
# ---------------------------------------------------------------------------


def test_pipeline_block_fatal_after_refine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Aplica solo un fix parcial: convocatoria_id sí, solicitante_id sigue mal.
    parcial = {**_ARGS_BAD, "convocatoria_id": "CONV-007"}
    fake = _FakeRefine(used_llm=True, repaired_args=parcial)
    monkeypatch.setattr(refine_mod, "refine", fake)

    result = pipeline.run_gate("crear_solicitud", _ARGS_BAD)

    assert result.status == "block"
    assert result.refine_used is True
    assert result.refine_reason == "fatal_after_refine"
    assert result.args_final == parcial
    assert result.issues_final != []


# ---------------------------------------------------------------------------
# Tool desconocida
# ---------------------------------------------------------------------------


def test_pipeline_tool_desconocida_lanza() -> None:
    with pytest.raises(UnknownToolError):
        pipeline.run_gate("borrar_todo", {})


# ---------------------------------------------------------------------------
# as_dict serializable
# ---------------------------------------------------------------------------


def test_gate_result_as_dict_incluye_todas_las_claves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        refine_mod, "refine", _FakeRefine(used_llm=False, reason="stub")
    )
    result = pipeline.run_gate("crear_solicitud", _ARGS_OK)
    d = result.as_dict()
    assert set(d.keys()) == {
        "status",
        "args_final",
        "issues_initial",
        "issues_final",
        "refine_used",
        "refine_reason",
    }
