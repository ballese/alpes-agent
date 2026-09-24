"""Orquestador del Juez: Critique → Refine → Validate.

Recibe un payload aislado (sin trace del ejecutor) y produce un veredicto:

    APPROVE  → el ejecutor sigue con los args originales.
    REFINE   → el ejecutor reemplaza los args por `refined_args`.
    REJECT   → el ejecutor NO ejecuta la tool y sintetiza un ToolMessage
               con la razón (fail-closed).

Diseño:
- 1 sola pasada de refinamiento (evita loops caros con qwen2.5:3b).
- JSON estricto: si el LLM no responde JSON válido, se convierte en REJECT.
- Verificaciones de contexto con tope duro de 1 llamada por tipo.
- Mismo modelo Ollama que el ejecutor (`settings.ollama_model`, temp=0):
  el laboratorio 15 pide reutilizar el LLM del proyecto.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from cli.config import get_settings
from judge.prompts import INTENT_ALIGNMENT_PROMPT, REFINER_PROMPT
from judge.rubric import is_critical, run_fast_rubric, run_full_rubric
from judge.verification import (
    lookup_policies,
    verify_convocatoria,
    verify_persona,
)
from observability.tracing import trazable


def _parse_json_strict(texto: str) -> dict | None:
    """Parseo estricto: si el modelo devuelve prosa, retornamos None y
    el llamador convierte eso en REJECT (fail-closed).
    """
    texto = (texto or "").strip()
    # Los modelos pequeños a veces envuelven en fences ```json; eso lo toleramos.
    if texto.startswith("```"):
        texto = texto.strip("`")
        if texto.lower().startswith("json"):
            texto = texto[4:].lstrip()
    try:
        data = json.loads(texto)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _make_llm() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )


def _gather_context(tool_name: str, args: dict[str, Any], auth: dict[str, Any]) -> dict:
    """Verificación independiente. Tope: 1 llamada por función de verificación."""
    contexto: dict[str, Any] = {
        "rol_verificado": None,
        "convocatoria": None,
        "politicas": None,
    }

    token = auth.get("token")
    persona_id_claimed = auth.get("persona_id")
    if token:
        persona = verify_persona(persona_id_claimed or "", token)
        contexto["rol_verificado"] = persona.get("rol") if persona.get("ok") else None
        contexto["persona_verify_ok"] = persona.get("ok", False)
        contexto["areas_expertise"] = persona.get("areas_expertise", [])

    conv_id = args.get("convocatoria_id")
    if conv_id and is_critical(tool_name):
        contexto["convocatoria"] = verify_convocatoria(conv_id)
        if tool_name in {"crear_solicitud", "asignar_convocatoria"}:
            contexto["politicas"] = lookup_policies(conv_id)

    return contexto


def _llm_intent_alignment(
    pregunta: str, tool_name: str, args: dict, contexto: dict
) -> dict:
    llm = _make_llm()
    prompt = INTENT_ALIGNMENT_PROMPT.format(
        pregunta=pregunta,
        tool_name=tool_name,
        args=json.dumps(args, ensure_ascii=False),
        contexto=json.dumps(contexto, ensure_ascii=False),
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    parsed = _parse_json_strict(
        resp.content if isinstance(resp.content, str) else str(resp.content)
    )
    if not parsed or parsed.get("verdict") not in {"APPROVE", "REFINE", "REJECT"}:
        return {
            "verdict": "REJECT",
            "reason": "R5: LLM no devolvió JSON válido (fail-closed)",
        }
    return {"verdict": parsed["verdict"], "reason": parsed.get("reason", "")}


def _llm_refine(
    pregunta: str, tool_name: str, args: dict, contexto: dict, razon: str
) -> dict | None:
    llm = _make_llm()
    prompt = REFINER_PROMPT.format(
        pregunta=pregunta,
        tool_name=tool_name,
        args=json.dumps(args, ensure_ascii=False),
        contexto=json.dumps(contexto, ensure_ascii=False),
        razon=razon,
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    parsed = _parse_json_strict(
        resp.content if isinstance(resp.content, str) else str(resp.content)
    )
    if not parsed or not isinstance(parsed.get("refined_args"), dict):
        return None
    return parsed


@trazable(name="judge_tool_call", run_type="chain", tags=["judge", "a2a"])
def judge_tool_call(payload: dict) -> dict:
    """Punto de entrada del Juez.

    payload = {
        "original_user_question": str,
        "proposed_action": {"tool_name": str, "args": dict},
        "authenticated_context": {"token": str | None,
                                  "persona_id": str | None,
                                  "rol_claimed": str | None},
    }

    Devuelve `{verdict, reason, refined_args?, trace: [str]}`.
    """
    trace: list[str] = []
    pregunta = payload.get("original_user_question", "")
    accion = payload.get("proposed_action") or {}
    auth = payload.get("authenticated_context") or {}
    tool_name = accion.get("tool_name", "")
    args = accion.get("args") or {}

    # 1) Tools de solo lectura: rúbrica rápida (solo R1).
    if not is_critical(tool_name):
        fast = run_fast_rubric(tool_name, args)
        trace.append(f"fast_rubric ok={fast.ok} reglas={fast.rules_run}")
        if not fast.ok:
            return {
                "verdict": "REJECT",
                "reason": "; ".join(fast.failures),
                "trace": trace,
            }
        return {
            "verdict": "APPROVE",
            "reason": "fast-path (solo lectura)",
            "trace": trace,
        }

    # 2) Tools críticas: rúbrica llena + verificación de contexto + R5.
    contexto = _gather_context(tool_name, args, auth)
    trace.append(
        f"contexto rol_verificado={contexto.get('rol_verificado')!r} "
        f"convocatoria_ok={(contexto.get('convocatoria') or {}).get('ok')}"
    )

    full = run_full_rubric(tool_name, args, contexto.get("rol_verificado"))
    trace.append(
        f"full_rubric ok={full.ok} reglas={full.rules_run} fallas={full.failures}"
    )
    if not full.ok:
        return {
            "verdict": "REJECT",
            "reason": "Rúbrica formal falló: " + "; ".join(full.failures),
            "trace": trace,
        }

    r5 = _llm_intent_alignment(pregunta, tool_name, args, contexto)
    trace.append(f"R5 verdict={r5['verdict']} reason={r5['reason']!r}")

    if r5["verdict"] == "APPROVE":
        return {"verdict": "APPROVE", "reason": r5["reason"], "trace": trace}

    if r5["verdict"] == "REJECT":
        return {"verdict": "REJECT", "reason": r5["reason"], "trace": trace}

    # REFINE: 1 sola pasada.
    refinado = _llm_refine(pregunta, tool_name, args, contexto, r5["reason"])
    if not refinado:
        trace.append("refine falló (JSON inválido) → REJECT")
        return {
            "verdict": "REJECT",
            "reason": "R5 pidió REFINE pero el refinador no produjo JSON válido",
            "trace": trace,
        }

    refined_args = refinado["refined_args"]
    trace.append(f"refine ok — cambios={refinado.get('reason', '')!r}")
    return {
        "verdict": "REFINE",
        "reason": refinado.get("reason", "argumentos refinados"),
        "refined_args": refined_args,
        "trace": trace,
    }
