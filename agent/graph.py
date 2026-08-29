"""Grafo del agente (laboratorios 4 y 5) — Centro de Proyectos y Consultoría.

Segunda etapa: agente con memoria persistente de dos capas y compresión de contexto.
- Memoria de corto plazo: persistencia con SqliteSaver indexada por thread_id.
- Memoria de largo plazo: persistencia con InMemoryStore indexada por namespaces ("profiles", user_id).
- Compresión de contexto: resumen progresivo de mensajes antiguos con RemoveMessage.
"""

import asyncio
import concurrent.futures
from typing import Annotated, Any, Dict, List, Literal, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore

from agent.memory.checkpointer import build_checkpointer
from agent.memory.store import build_store
from cli.config import get_settings
from observability.tracing import trazable

# Umbral de compresión: al superar 6 mensajes se dispara el resumen progresivo
COMPRESSION_THRESHOLD = 6


class AgentState(TypedDict):
    """Estado compartido con mensajes, identidad de usuario, perfil y resumen."""

    messages: Annotated[List[BaseMessage], add_messages]
    user_id: str
    profile: str
    summary: str


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
    "con el token resultante, usa consultar_mi_perfil cuando pida su perfil o cuando debas "
    "validar rol, dedicación, experticia o riesgo. "
    "Si el usuario quiere postularse, primero consulta convocatoria, políticas y perfil; "
    "si no hay riesgo claro, usa crear_solicitud; si hay riesgo o ambigüedad importante, usa escalar. "
    "Si el usuario es directivo y pide asignar equipo, consulta la información necesaria y luego "
    "usa asignar_convocatoria. "
    "Si la pregunta está fuera del dominio del Centro de Proyectos, responde brevemente sin tools."
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


def _asegurar_tool_sincrona(tool):
    """Permite que herramientas asíncronas (como las de FastMCP) se invoquen en ToolNode síncrono."""
    if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
        coro = tool.coroutine

        def _sync_func(*args, **kwargs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro(*args, **kwargs)).result()

        tool.func = _sync_func
    return tool


def profile_loader(state: AgentState, store: BaseStore) -> Dict[str, Any]:
    """Carga el perfil de largo plazo del investigador desde el Store."""
    user_id = state.get("user_id", "default_user")
    item = store.get(("profiles", user_id), "profile")
    if not item:
        return {"profile": ""}
    perfil = item.value
    resumen = (
        f"Nombre: {perfil.get('nombre', user_id)}. "
        f"Área: {perfil.get('area', 'No especificada')}. "
        f"Preferencias: {perfil.get('preferencias', '')}."
    )
    return {"profile": resumen}


def profile_updater(state: AgentState, store: BaseStore) -> Dict[str, Any]:
    """Extrae hechos permanentes del mensaje del usuario y actualiza el Store."""
    user_id = state.get("user_id", "default_user")
    human_msgs = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not human_msgs:
        return {}

    last_msg = human_msgs[-1].content
    settings = get_settings()
    llm_extractor = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )
    prompt = (
        "Extrae únicamente hechos permanentes sobre el perfil del investigador (nombre, rol, "
        f"área temática, intereses de proyectos) del mensaje: '{last_msg}'. "
        "Si no hay datos personales relevantes para su perfil a largo plazo, responde exactamente: 'NADA'. "
        "Si hay datos, escribe una frase breve y directa."
    )
    extraccion = llm_extractor.invoke([HumanMessage(content=prompt)])
    fact = extraccion.content.strip()

    if "NADA" in fact or not fact:
        return {}

    namespace = ("profiles", user_id)
    existente = store.get(namespace, "profile")
    data = existente.value if existente else {}
    pref_actual = data.get("preferencias", "")
    data["preferencias"] = f"{pref_actual} {fact}".strip() if pref_actual else fact
    store.put(namespace, "profile", data)
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
    remove_ops = [RemoveMessage(id=m.id) for m in to_summarize if getattr(m, "id", None)]

    return {"messages": remove_ops, "summary": new_summary.content}


@trazable(name="nodo_decision", run_type="chain", tags=["langgraph"])
def _debe_ejecutar_tools(state: AgentState) -> Literal["tools", "profile_updater"]:
    """Determina si el modelo llamó a herramientas o si pasa a actualizar perfil."""
    ultimo = state["messages"][-1] if state.get("messages") else None
    if isinstance(ultimo, AIMessage) and ultimo.tool_calls:
        return "tools"
    return "profile_updater"


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
    def ejecutar_tools(state: AgentState, config=None) -> dict:
        return tool_node.invoke(state, config=config)

    graph = StateGraph(AgentState)
    graph.add_node("profile_loader", profile_loader)
    graph.add_node("agente", agente)
    graph.add_node("tools", ejecutar_tools)
    graph.add_node("profile_updater", profile_updater)
    graph.add_node("summarize", summarize_node)

    graph.add_edge(START, "profile_loader")
    graph.add_edge("profile_loader", "agente")

    graph.add_conditional_edges(
        "agente",
        _debe_ejecutar_tools,
        {"tools": "tools", "profile_updater": "profile_updater"},
    )
    graph.add_edge("tools", "agente")

    graph.add_conditional_edges(
        "profile_updater",
        _should_compress,
        {"summarize": "summarize", "__end__": END},
    )
    graph.add_edge("summarize", END)

    saver = checkpointer if checkpointer is not None else build_checkpointer()
    store_inst = store if store is not None else build_store()

    return graph.compile(checkpointer=saver, store=store_inst)
