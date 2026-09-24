"""Nodo `judge_gate` — inserta al Juez entre la decisión del agente y la
ejecución de la herramienta.

Punto de aislamiento: aquí construimos el payload que va al Juez a partir
del `state` del ejecutor. SOLO se pasan tres cosas:

    original_user_question   → el ÚLTIMO HumanMessage (turno actual).
    proposed_action          → nombre de tool + args del ÚLTIMO AIMessage.
    authenticated_context    → token, persona_id, rol_claimed extraídos de
                                los ToolMessages ya presentes en el estado.

NUNCA se pasan: reasoning_trace, summary, profile, historial completo.

Manejo del veredicto:
- APPROVE  → devolvemos {} (no cambia el estado): el flujo pasa a tools.
- REFINE   → reemplazamos las tool_calls del último AIMessage con los
             `refined_args` (preservando id/name). Es una edición de mensaje,
             no una regeneración del LLM.
- REJECT   → sintetizamos un ToolMessage con `content=<razón>` por cada
             tool_call pendiente y saltamos la ejecución. El agente verá
             la razón como observación y decidirá qué hacer.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from judge.a2a_client import solicit_verdict
from observability.tracing import trazable


def _latest_human_question(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            return content if isinstance(content, str) else str(content)
    return ""


def _extract_auth_context(messages: list) -> dict[str, Any]:
    """Escanea ToolMessages ya presentes para armar el contexto autenticado.

    Confiamos en `autenticarse_centro` (token, rol) y `consultar_mi_perfil`
    (persona_id). El `rol` de autenticarse es un CLAIM: solo se guarda como
    `rol_claimed`; la verdad la produce el Juez con verify_persona.
    """
    ctx: dict[str, Any] = {"token": None, "persona_id": None, "rol_claimed": None}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            data = (
                json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            )
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if msg.name == "autenticarse_centro":
            ctx["token"] = data.get("token") or ctx["token"]
            ctx["rol_claimed"] = data.get("rol") or ctx["rol_claimed"]
        elif msg.name in {"consultar_mi_perfil", "consultar_mi_perfil_local"}:
            ctx["persona_id"] = data.get("id") or ctx["persona_id"]
    return ctx


def _build_verdict_trace_line(tool_name: str, verdict: dict) -> str:
    v = verdict.get("verdict", "?")
    r = verdict.get("reason", "")
    return f"[juez] {tool_name}: {v} — {r}"


@trazable(name="nodo_judge_gate", run_type="chain", tags=["judge", "gate"])
def judge_gate(state: dict) -> dict:
    """Nodo LangGraph. Devuelve un update parcial del estado.

    Es genérico sobre la forma del estado: sirve para `AgentState` y para
    `ReActState` porque ambos exponen `messages`. El campo `judge_trace`
    se crea si no existe (reducer aditivo en cada grafo).
    """
    messages: list = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        return {}
    ai = messages[-1]
    if not getattr(ai, "tool_calls", None):
        return {}

    pregunta = _latest_human_question(messages)
    auth_ctx = _extract_auth_context(messages)

    nuevos_tool_calls: list[dict] = []
    tool_messages_rechazo: list[ToolMessage] = []
    trace_lines: list[str] = []
    hubo_refine = False

    for call in ai.tool_calls:
        name = call["name"]
        args = call.get("args") or {}

        verdict = solicit_verdict(
            tool_name=name,
            args=args,
            context=auth_ctx,
            original_user_question=pregunta,
        )
        trace_lines.append(_build_verdict_trace_line(name, verdict))

        if verdict["verdict"] == "APPROVE":
            nuevos_tool_calls.append(call)
        elif verdict["verdict"] == "REFINE":
            hubo_refine = True
            refined_args = verdict.get("refined_args") or args
            nuevos_tool_calls.append(
                {"name": name, "args": refined_args, "id": call["id"]}
            )
        else:  # REJECT
            tool_messages_rechazo.append(
                ToolMessage(
                    content=(
                        f"[JUEZ RECHAZÓ la llamada a {name}] "
                        f"{verdict.get('reason', 'sin razón')}. "
                        "No se ejecutó. Considera esta observación al decidir el siguiente paso."
                    ),
                    name=name,
                    tool_call_id=call["id"],
                )
            )

    # Caso 1: todas rechazadas → devolvemos solo los ToolMessages de rechazo.
    # El agente verá las razones y decidirá; no ejecutamos nada.
    if not nuevos_tool_calls and tool_messages_rechazo:
        return {
            "messages": tool_messages_rechazo,
            "judge_trace": trace_lines,
        }

    # Caso 2: hubo REFINE → reemplazamos el AIMessage entero conservando su id.
    if hubo_refine or (tool_messages_rechazo and nuevos_tool_calls):
        ai_editado = AIMessage(
            content=ai.content,
            tool_calls=nuevos_tool_calls,
            id=ai.id,
        )
        # add_messages usa el id como clave: emitir con el mismo id sustituye.
        return {
            "messages": [ai_editado, *tool_messages_rechazo],
            "judge_trace": trace_lines,
        }

    # Caso 3: todas APPROVE → solo registramos la traza.
    return {"judge_trace": trace_lines}
