"""Grafo del agente — Centro de Proyectos y Consultoría.

Segunda etapa: agente con memoria persistente de dos capas y compresión de contexto.
- Memoria de corto plazo: checkpoints PostgreSQL indexados por thread_id.
- Memoria de largo plazo: perfil único persistido en PostgreSQL.
- Compresión de contexto: resumen progresivo de mensajes antiguos con RemoveMessage.
"""

import asyncio
import concurrent.futures
import json
import operator
from typing import Annotated, Any, Dict, List, Literal, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore

from agent.judge_gate import judge_gate
from agent.memory.store import SINGLE_USER_ID, save_user_profile
from cli.config import get_settings
from observability.tracing import trazable

# Umbral de compresión: al superar 6 mensajes se dispara el resumen progresivo
COMPRESSION_THRESHOLD = 6


class AgentState(TypedDict):
    """Estado compartido con mensajes, identidad de usuario, perfil, resumen y traza del Juez."""

    messages: Annotated[List[BaseMessage], add_messages]
    user_id: str
    profile: str
    summary: str
    judge_trace: Annotated[List[str], operator.add]


SYSTEM_PROMPT_BASE = (
    "Responde SIEMPRE en español. "
    "Eres el asistente del Centro de Proyectos y Consultoría de la Universidad "
    "de los Andes. Ayudas al personal a evaluar convocatorias de investigación "
    "y a los directivos a conformar equipos. Usa las herramientas disponibles "
    "para consultar convocatorias, políticas, personal e historial: no "
    "inventes datos que deberían venir de una herramienta. "
    "Si el usuario pregunta por convocatorias, usa buscar_convocatoria con un query breve. "
    "Si ya tienes un id de convocatoria y necesita reglas internas, usa leer_politicas_universidad. "
    "Si el usuario entrega cédula y clave, invoca inmediatamente autenticarse_centro; "
    "cuando autenticarse_centro retorne el campo 'token', úsalo directamente como argumento "
    "'token' de consultar_mi_perfil; nunca le pidas al usuario que repita ese token. "
    "Usa consultar_mi_perfil cuando pida su perfil o cuando debas validar rol, dedicación, "
    "experticia o riesgo. "
    "Si el usuario quiere postularse, primero consulta convocatoria, políticas y perfil; "
    "si no hay riesgo claro, usa crear_solicitud; si hay riesgo o ambigüedad importante, usa escalar. "
    "Si el usuario es directivo y pide asignar equipo, consulta la información necesaria y luego "
    "usa asignar_convocatoria. "
    "Si la pregunta está fuera del dominio del Centro de Proyectos, responde brevemente sin tools.\n\n"
    "REGLAS DE OPERACIÓN MULTI-PASO (OBLIGATORIAS):\n"
    "- Resuelve las solicitudes encadenando de forma autónoma todas las herramientas necesarias "
    "una tras otra, sin detenerte a pedir confirmación ni permiso al usuario entre pasos.\n"
    "- Si autenticarse_centro ya retornó un 'token', el usuario YA ESTÁ AUTENTICADO. "
    "Usa ese token inmediatamente en consultar_mi_perfil.\n"
    "- Tras ejecutar consultar_mi_perfil, extrae los temas de 'areas_expertise' e invoca "
    "INMEDIATAMENTE buscar_convocatoria(query=<esos temas de experticia>) en el mismo turno.\n"
    "- Solo responde con texto al usuario cuando buscar_convocatoria haya retornado los resultados, "
    "presentando un resumen claro de las convocatorias que encajan con su perfil."
)


def _resumir_estado(inputs: dict) -> dict:
    """Extrae metadatos seguros de entrada para las trazas de LangSmith."""
    if not isinstance(inputs, dict):
        return {}
    state = inputs.get("state", inputs)
    messages = state.get("messages", []) if isinstance(state, dict) else []
    return {
        "messages_total": len(messages),
        "ultimo_tipo": messages[-1].__class__.__name__ if messages else None,
    }


def _resumir_salida(outputs: dict) -> dict:
    """Extrae metadatos seguros de salida para las trazas de LangSmith."""
    if not isinstance(outputs, dict):
        return {}
    messages = outputs.get("messages", []) if isinstance(outputs, dict) else []
    return {"messages_total": len(messages)}


def _json_o_none(texto: str) -> Any:
    try:
        return json.loads(texto)
    except (TypeError, json.JSONDecodeError):
        return None


def _contenido_tool(message: ToolMessage) -> Any:
    content = message.content
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    if isinstance(content, str):
        return _json_o_none(content) or content
    return content


def _recordar_perfil_desde_tools(outputs: dict, store: BaseStore) -> None:
    for message in outputs.get("messages", []):
        if not isinstance(message, ToolMessage):
            continue
        if message.name not in {"consultar_mi_perfil", "consultar_mi_perfil_local"}:
            continue

        perfil = _contenido_tool(message)
        if not isinstance(perfil, dict) or "error" in perfil:
            continue

        areas = perfil.get("areas_expertise", [])
        areas_txt = ", ".join(areas) if isinstance(areas, list) else str(areas)
        save_user_profile(
            store,
            SINGLE_USER_ID,
            {
                "persona_id": perfil.get("id"),
                "nombre_completo": perfil.get("nombre_completo"),
                "rol": perfil.get("rol"),
                "seccion": perfil.get("seccion"),
                "areas_expertise": areas,
                "nivel": perfil.get("nivel"),
                "dedicacion": perfil.get("dedicacion"),
                "riesgo": perfil.get("riesgo"),
                "continuidad": (
                    f"El usuario autenticado es {perfil.get('nombre_completo')} "
                    f"con rol {perfil.get('rol')} y experticia en {areas_txt}."
                ),
            },
        )


def _asegurar_tool_sincrona(tool):
    """Permite que herramientas asíncronas (como las de FastMCP) se invoquen en ToolNode síncrono."""
    if (
        getattr(tool, "func", None) is None
        and getattr(tool, "coroutine", None) is not None
    ):
        coro = tool.coroutine

        def _sync_func(*args, **kwargs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro(*args, **kwargs)).result()

        tool.func = _sync_func
    return tool


def profile_loader(state: AgentState, store: BaseStore) -> Dict[str, Any]:
    """Carga el perfil único de largo plazo desde el Store."""
    item = store.get(("profiles", SINGLE_USER_ID), "profile")
    if not item:
        return {"profile": ""}
    perfil = item.value
    areas = perfil.get("areas_expertise") or perfil.get("area") or "No especificada"
    if isinstance(areas, list):
        areas = ", ".join(areas)
    resumen = (
        f"Nombre: {perfil.get('nombre_completo') or perfil.get('nombre') or SINGLE_USER_ID}. "
        f"Rol: {perfil.get('rol', 'No especificado')}. "
        f"Área: {areas}. "
        f"Preferencias: {perfil.get('preferencias', '')}. "
        f"Continuidad: {perfil.get('continuidad', '')}."
    )
    return {"profile": resumen}


def profile_updater(state: AgentState, store: BaseStore) -> Dict[str, Any]:
    """Extrae hechos permanentes del mensaje y actualiza el perfil único."""
    human_msgs = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not human_msgs:
        return {}

    last_msg = human_msgs[-1].content
    recientes = state.get("messages", [])[-6:]
    contexto = "\n".join(
        f"{msg.__class__.__name__}: {getattr(msg, 'content', '')}"
        for msg in recientes
        if getattr(msg, "content", "")
    )
    settings = get_settings()
    llm_extractor = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )
    prompt = (
        "Extrae memoria útil para continuar futuras conversaciones del mismo usuario. "
        "Incluye solo hechos estables o contexto de negocio vigente: rol, intereses, "
        "convocatoria en evaluación, restricciones relevantes o siguiente paso pendiente. "
        f"Último mensaje humano: '{last_msg}'.\n"
        f"Contexto reciente:\n{contexto}\n"
        "Si no hay nada útil para recordar, responde exactamente: 'NADA'. "
        "Si hay datos, escribe una sola frase breve."
    )
    extraccion = llm_extractor.invoke([HumanMessage(content=prompt)])
    fact = extraccion.content.strip()

    if "NADA" in fact or not fact:
        return {}

    existente = store.get(("profiles", SINGLE_USER_ID), "profile")
    data = existente.value if existente else {}
    continuidad_actual = data.get("continuidad", "")
    data["continuidad"] = (
        f"{continuidad_actual} {fact}".strip() if continuidad_actual else fact
    )
    save_user_profile(store, SINGLE_USER_ID, data)
    return {}


def summarize_node(state: AgentState) -> Dict[str, Any]:
    """Comprime los mensajes antiguos en un resumen y los elimina con RemoveMessage."""
    messages = state.get("messages", [])
    existing_summary = state.get("summary", "")

    to_summarize = messages[:-2]
    if not to_summarize:
        return {}

    convo_text = "\n".join(
        f"{'Usuario' if isinstance(m, HumanMessage) else 'Asistente'}: {m.content}"
        for m in to_summarize
    )

    settings = get_settings()
    llm_summarizer = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )

    if existing_summary:
        prompt = (
            f"Resumen existente de la conversación:\n{existing_summary}\n\n"
            f"Nuevos turnos a incorporar:\n{convo_text}\n\n"
            "Escribe un resumen consolidado y conciso de toda la conversación."
        )
    else:
        prompt = f"Resume concisamente la siguiente conversación sobre convocatorias:\n\n{convo_text}"

    new_summary = llm_summarizer.invoke([HumanMessage(content=prompt)])
    remove_ops = [
        RemoveMessage(id=m.id) for m in to_summarize if getattr(m, "id", None)
    ]

    return {"messages": remove_ops, "summary": new_summary.content}


@trazable(name="nodo_decision", run_type="chain", tags=["langgraph"])
def _debe_ejecutar_tools(state: AgentState) -> Literal["judge_gate", "profile_updater"]:
    """Determina si el modelo llamó a herramientas o si pasa a actualizar perfil.

    Nota: aunque haya tool_calls, no vamos directo a `tools`; primero pasa por
    `judge_gate`, que puede aprobar, refinar o rechazar cada llamada.
    """
    ultimo = state["messages"][-1] if state.get("messages") else None
    if isinstance(ultimo, AIMessage) and ultimo.tool_calls:
        return "judge_gate"
    return "profile_updater"


def _post_judge(state: AgentState) -> Literal["tools", "agente"]:
    """Después del Juez, ¿queda algo por ejecutar?

    Sí, si el último AIMessage con tool_calls tiene alguno cuyo id NO ha sido
    respondido aún con un ToolMessage (i.e., el Juez no lo rechazó). Si el
    Juez rechazó TODAS las llamadas, ya hay ToolMessages para todas y vamos
    de vuelta a `agente` para que decida el siguiente paso.
    """
    messages = state.get("messages", [])
    # Buscar el AIMessage con tool_calls más reciente.
    pending: set[str] = set()
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            pending = {tc["id"] for tc in msg.tool_calls}
            break
    # Descontar los ids ya respondidos por ToolMessages posteriores.
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id in pending:
            pending.discard(msg.tool_call_id)
    return "tools" if pending else "agente"


def _should_compress(state: AgentState) -> Literal["summarize", "__end__"]:
    """Evalúa si el historial de mensajes superó el umbral de compresión."""
    if len(state.get("messages", [])) > COMPRESSION_THRESHOLD:
        return "summarize"
    return "__end__"


def build_graph(tools: list | None = None, checkpointer=None, store=None):
    """Compila y devuelve el grafo con memoria de dos capas y compresión."""
    tools = [_asegurar_tool_sincrona(t) for t in (tools or [])]

    settings = get_settings()
    language_model = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )
    model_with_tools = language_model.bind_tools(tools)
    tool_node = ToolNode(tools)

    @trazable(
        name="nodo_agente",
        run_type="chain",
        tags=["langgraph", "agente"],
        process_inputs=_resumir_estado,
        process_outputs=_resumir_salida,
    )
    def agente(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        profile = state.get("profile", "")
        summary = state.get("summary", "")

        system_parts = [SYSTEM_PROMPT_BASE]
        if profile:
            system_parts.append(
                f"INFORMACIÓN PERSISTENTE DEL USUARIO (Memoria de Largo Plazo):\n{profile}\n"
                "Usa esta información para personalizar respuestas sin solicitar que repita sus datos."
            )
        if summary:
            system_parts.append(
                f"RESUMEN DE LA CONVERSACIÓN PREVIA (Contexto Comprimido):\n{summary}"
            )

        context = [SystemMessage(content="\n\n".join(system_parts))] + messages
        respuesta = model_with_tools.invoke(context)
        return {"messages": [respuesta]}

    @trazable(
        name="nodo_tools",
        run_type="chain",
        tags=["langgraph", "tools"],
        process_inputs=_resumir_estado,
        process_outputs=_resumir_salida,
    )
    def ejecutar_tools(state: AgentState, store: BaseStore, config=None) -> dict:
        outputs = tool_node.invoke(state, config=config)
        _recordar_perfil_desde_tools(outputs, store)
        return outputs

    graph = StateGraph(AgentState)
    graph.add_node("profile_loader", profile_loader)
    graph.add_node("agente", agente)
    graph.add_node("judge_gate", judge_gate)
    graph.add_node("tools", ejecutar_tools)
    graph.add_node("profile_updater", profile_updater)
    graph.add_node("summarize", summarize_node)

    graph.add_edge(START, "profile_loader")
    graph.add_edge("profile_loader", "agente")

    graph.add_conditional_edges(
        "agente",
        _debe_ejecutar_tools,
        {"judge_gate": "judge_gate", "profile_updater": "profile_updater"},
    )
    graph.add_conditional_edges(
        "judge_gate",
        _post_judge,
        {"tools": "tools", "agente": "agente"},
    )
    graph.add_edge("tools", "agente")

    graph.add_conditional_edges(
        "profile_updater",
        _should_compress,
        {"summarize": "summarize", "__end__": END},
    )
    graph.add_edge("summarize", END)

    # `checkpointer` y `store` los inyecta quien construye el grafo: el CLI pasa
    # los de PostgreSQL (memoria real). Si llegan como None el grafo compila
    # igual, sin memoria persistente, tal como documenta contract.py. Así las
    # pruebas de forma (semana 2) no necesitan una base de datos levantada.
    return graph.compile(checkpointer=checkpointer, store=store)
