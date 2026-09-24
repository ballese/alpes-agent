"""Pipeline **Critique -> Refine -> Validate** del write-gate.

Contrato de alto nivel::

    run_gate(tool, args) -> GateResult

Estados posibles:

* ``pass``            - las reglas no encontraron issues fatales sobre los
                        args originales; el agente puede ejecutar la tool tal
                        cual.
* ``refine-passed``   - los args originales tenían issues fatales, el LLM
                        refine los reparó y una segunda ronda de reglas los
                        aceptó. Se devuelven ``args_final`` distintos.
* ``block``           - había issues fatales y el refine no logró resolverlos
                        (bien porque el LLM no está disponible, bien porque los
                        args reparados siguen fallando la validación).

En todos los casos ``GateResult`` incluye la traza completa (issues iniciales,
si se usó el LLM y su reason en caso de fallback, e issues finales) para que
la UI del agente pueda mostrarla.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from judge.gate import refine as refine_mod
from judge.gate import rules
from judge.gate.rules import Issue


@dataclass(frozen=True)
class GateResult:
    """Salida del pipeline CRV para una tool crítica.

    Attributes:
        status:            ``"pass"`` | ``"refine-passed"`` | ``"block"``.
        args_final:        args que el agente debe ejecutar si ``status != "block"``.
        issues_initial:    hallazgos de la primera ronda de crítica.
        issues_final:      hallazgos de la segunda ronda (solo si hubo refine).
        refine_used:       True si el LLM produjo args reparados.
        refine_reason:     motivo del fallback del refine, si aplica.
    """

    status: str
    args_final: dict[str, Any]
    issues_initial: list[Issue] = field(default_factory=list)
    issues_final: list[Issue] = field(default_factory=list)
    refine_used: bool = False
    refine_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "args_final": self.args_final,
            "issues_initial": [i.as_dict() for i in self.issues_initial],
            "issues_final": [i.as_dict() for i in self.issues_final],
            "refine_used": self.refine_used,
            "refine_reason": self.refine_reason,
        }


class UnknownToolError(ValueError):
    """La tool solicitada no está registrada en ``rules.CHECKERS``."""


def run_gate(tool: str, args: dict[str, Any]) -> GateResult:
    """Ejecuta Crítica -> (Refine si hay fatales) -> Re-crítica.

    Raises:
        UnknownToolError: si ``tool`` no es una tool crítica reconocida.
    """
    checker = rules.CHECKERS.get(tool)
    if checker is None:
        raise UnknownToolError(
            f"tool '{tool}' no está registrada como crítica de escritura"
        )

    issues_initial = checker(args)

    # Ruta feliz: no hay fatales -> pasamos los args originales tal cual.
    if not rules.has_fatal(issues_initial):
        return GateResult(
            status="pass",
            args_final=args,
            issues_initial=issues_initial,
        )

    # Hay fatales: pedimos al LLM que repare.
    refine_result = refine_mod.refine(tool, args, issues_initial)

    # Si el LLM no reparó nada (fallback), no vale la pena re-validar los
    # mismos args: sabemos que van a fallar. Bloqueamos directo.
    if not refine_result.used_llm:
        return GateResult(
            status="block",
            args_final=args,
            issues_initial=issues_initial,
            issues_final=issues_initial,
            refine_used=False,
            refine_reason=refine_result.reason,
        )

    # Re-crítica sobre los args reparados.
    issues_final = checker(refine_result.args)
    if rules.has_fatal(issues_final):
        return GateResult(
            status="block",
            args_final=refine_result.args,
            issues_initial=issues_initial,
            issues_final=issues_final,
            refine_used=True,
            refine_reason="fatal_after_refine",
        )

    return GateResult(
        status="refine-passed",
        args_final=refine_result.args,
        issues_initial=issues_initial,
        issues_final=issues_final,
        refine_used=True,
    )
