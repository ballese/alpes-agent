"""Rúbrica determinista del Juez — puro Python, sin LLM.

Cinco reglas de laboratorio 15 aterrizadas al caso Centro de Proyectos:

- R1  Prompt injection: la `justificacion` o el `query` no debe contener
      marcadores de instrucciones (típicos vectores).
- R2  Forma de IDs: `convocatoria_id` debe cumplir `CONV-\\d+`, personas `PER-\\d+`.
- R3  Autorización mínima: `asignar_convocatoria` exige rol `directivo`
      (el `rol_verificado` viene de `verify_persona`, no del claim).
- R4  Consistencia enumerada: `escalar.etapa_alcanzada` debe estar en el
      enum de la API (`escaneo_inicial | contraste_requisitos | conformacion_equipo`).
- R5  Alineación con intención: la queda en `judge/agent.py` (necesita LLM).

`run_fast_rubric` corre solo lo determinista y barato — se usa en tools de
solo lectura. `run_full_rubric` corre TODO lo determinista (R1–R4) y la
rúbrica llena se completa con R5 en `judge/agent.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# R1: patrones típicos de inyección de prompt. No pretenden ser exhaustivos,
# solo bloquear los vectores obvios que un modelo pequeño podría obedecer.
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all|previous|the above) instructions?", re.IGNORECASE),
    re.compile(r"olvida (todas |las )?instrucciones", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"###\s*system", re.IGNORECASE),
    re.compile(r"</?\s*system\s*>", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"actúa como (un )?(administrador|root|directivo)", re.IGNORECASE),
]

# R2: forma canónica de los IDs — la API empresarial usa `CONV-\d+`, `PER-\d+`,
# `SOL-\d+` (ver agent/tools.py). Un desajuste aquí casi siempre es una
# alucinación del ejecutor.
ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "convocatoria_id": re.compile(r"^CONV-\d+$"),
    "solicitante_id": re.compile(r"^PER-\d+$"),
    "directivo_id": re.compile(r"^PER-\d+$"),
}

# R4: etapas válidas de escalamiento (ver agent/tools.py:escalar).
ETAPAS_ESCALAMIENTO: set[str] = {
    "escaneo_inicial",
    "contraste_requisitos",
    "conformacion_equipo",
}

# Herramientas críticas (sí requieren rúbrica llena + R5). El resto son lectura.
CRITICAL_TOOLS: set[str] = {"crear_solicitud", "asignar_convocatoria", "escalar"}


@dataclass
class RubricReport:
    """Reporte de rúbrica: `ok=True` si TODAS las reglas ejecutadas pasaron."""

    ok: bool
    failures: list[str] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)

    def fail(self, rule: str, detail: str) -> None:
        self.ok = False
        self.failures.append(f"{rule}: {detail}")

    def ran(self, rule: str) -> None:
        self.rules_run.append(rule)


def _texto_libre(args: dict[str, Any]) -> list[str]:
    """Textos que podrían venir del usuario (candidatos a inyección)."""
    campos = ("justificacion", "query", "pregunta")
    return [str(args.get(c, "")) for c in campos if args.get(c)]


def _check_injection(report: RubricReport, args: dict[str, Any]) -> None:
    report.ran("R1")
    for texto in _texto_libre(args):
        for patron in INJECTION_PATTERNS:
            if patron.search(texto):
                report.fail(
                    "R1",
                    f"posible inyección detectada ({patron.pattern!r}) en campo de texto libre",
                )
                return


def _check_id_shape(report: RubricReport, args: dict[str, Any]) -> None:
    report.ran("R2")
    for campo, patron in ID_PATTERNS.items():
        valor = args.get(campo)
        if valor is None:
            continue
        if not isinstance(valor, str) or not patron.match(valor):
            report.fail("R2", f"{campo}={valor!r} no cumple {patron.pattern}")
    # equipo_asignado y equipo_sugerido son listas de PER-\d+
    for campo in ("equipo_asignado", "equipo_sugerido"):
        valores = args.get(campo)
        if not valores:
            continue
        if not isinstance(valores, list):
            report.fail("R2", f"{campo} debería ser lista")
            continue
        for v in valores:
            if not isinstance(v, str) or not ID_PATTERNS["solicitante_id"].match(v):
                report.fail("R2", f"{campo} contiene {v!r} que no es PER-\\d+")


def _check_role(
    report: RubricReport, tool_name: str, rol_verificado: str | None
) -> None:
    report.ran("R3")
    if tool_name == "asignar_convocatoria" and rol_verificado != "directivo":
        report.fail(
            "R3",
            f"asignar_convocatoria exige rol_verificado='directivo' (recibido {rol_verificado!r})",
        )


def _check_enum(report: RubricReport, tool_name: str, args: dict[str, Any]) -> None:
    report.ran("R4")
    if tool_name == "escalar":
        etapa = args.get("etapa_alcanzada")
        if etapa not in ETAPAS_ESCALAMIENTO:
            report.fail(
                "R4",
                f"etapa_alcanzada={etapa!r} no está en {sorted(ETAPAS_ESCALAMIENTO)}",
            )


def run_fast_rubric(tool_name: str, args: dict[str, Any]) -> RubricReport:
    """Rúbrica *fast-path* para tools de lectura: solo R1 (inyección)."""
    report = RubricReport(ok=True)
    _check_injection(report, args)
    return report


def run_full_rubric(
    tool_name: str, args: dict[str, Any], rol_verificado: str | None
) -> RubricReport:
    """Rúbrica llena para tools críticas: R1 + R2 + R3 + R4 (R5 va en el agente)."""
    report = RubricReport(ok=True)
    _check_injection(report, args)
    _check_id_shape(report, args)
    _check_role(report, tool_name, rol_verificado)
    _check_enum(report, tool_name, args)
    return report


def is_critical(tool_name: str) -> bool:
    return tool_name in CRITICAL_TOOLS
