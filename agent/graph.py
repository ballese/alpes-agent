"""Grafo del agente (laboratorios 4 y 5) — Centro de Proyectos y Consultoría.

Primera etapa: agente LINEAL con un ciclo `agente ⇄ tools`. El nodo "agente"
invoca al modelo local con las herramientas vinculadas (LCEL: prompt | modelo
con tools); si la respuesta trae `tool_calls`, se enruta al nodo "tools"
(`ToolNode` de LangGraph, que ejecuta las tools y produce un `ToolMessage`
por llamada); el resultado vuelve a "agente" hasta que el modelo responde
sin pedir más herramientas.

El estado es solo la lista de mensajes de la conversación (reductor
`add_messages`, igual que el `MessagesState` que usa el CLI en `cli/main.py`
al invocar `graph.astream({"messages": historia}, ...)`).
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from cli.config import get_settings
from observability.tracing import trazable


class AgentState(TypedDict):
    """Estado compartido del agente: solo la conversación.

    `add_messages` es el reductor que hace que cada nodo pueda retornar
    `{"messages": [nuevo_mensaje]}` sin tener que reescribir el historial
    completo — LangGraph anexa en lugar de reemplazar.
    """

    messages: Annotated[list, add_messages]


SYSTEM_PROMPT = (
    "Eres el asistente del Centro de Proyectos y Consultoría de la Universidad "
    "de los Alpes. Ayudas al personal a evaluar convocatorias de investigación "
    "y a los directivos a conformar equipos. Usa las herramientas disponibles "
    "para consultar convocatorias, políticas, personal e historial: no "
    "inventes datos que deberían venir de una herramienta. Si una acción "
    "requiere autenticación, pide primero cédula y clave."
)

# Cadena LCEL: prompt (con el historial como placeholder) -> modelo con tools
# vinculadas. bind_tools() adjunta el JSON Schema de cada tool al modelo, así
# el modelo puede responder con tool_calls en lugar de (o además de) texto.
agent_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("placeholder", "{messages}"),
    ]
)


@trazable(name="nodo_decision", run_type="chain", tags=["langgraph"])
def _debe_ejecutar_tools(state: AgentState) -> str:
    """Arista condicional: ¿el último mensaje del modelo pidió herramientas?

    Devuelve "tools" si el último mensaje es un AIMessage con tool_calls, o
    END si el modelo ya respondió con una respuesta final en texto.
    """
    ultimo = state["messages"][-1]
    if isinstance(ultimo, AIMessage) and ultimo.tool_calls:
        return "tools"
    return END


def _resumir_estado(inputs: dict) -> dict:
    state = inputs.get("state", {})
    messages = state.get("messages", []) if isinstance(state, dict) else []
    return {
        "messages_total": len(messages),
        "ultimo_tipo": messages[-1].__class__.__name__ if messages else None,
    }


def _resumir_salida(outputs: dict) -> dict:
    messages = outputs.get("messages", []) if isinstance(outputs, dict) else []
    return {"messages_total": len(messages)}


def build_graph(tools: list | None = None, checkpointer=None):
    """Compila y devuelve el grafo del agente, listo para invocar.

    Parámetros:
        tools:        herramientas disponibles para el agente (locales + MCP).
                       Si es None (por ejemplo, `contract.build_agent_graph()`
                       sin argumentos), el agente compila sin tools.
        checkpointer: memoria de corto plazo (se usa desde la semana 4). Si es
                      None, el grafo funciona igual pero sin persistencia.
    """
    tools = tools or []

    settings = get_settings()
    language_model = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )
    agent_chain = agent_prompt | language_model.bind_tools(tools)
    tool_node = ToolNode(tools)

    @trazable(
        name="nodo_agente",
        run_type="chain",
        tags=["langgraph", "agente"],
        process_inputs=_resumir_estado,
        process_outputs=_resumir_salida,
    )
    def agente(state: AgentState) -> dict:
        respuesta = agent_chain.invoke({"messages": state["messages"]})
        return {"messages": [respuesta]}

    @trazable(
        name="nodo_tools",
        run_type="chain",
        tags=["langgraph", "tools"],
        process_inputs=_resumir_estado,
        process_outputs=_resumir_salida,
    )
    async def ejecutar_tools(state: AgentState, config=None) -> dict:
        return await tool_node.ainvoke(state, config=config)

    graph = StateGraph(AgentState)
    graph.add_node("agente", agente)
    graph.add_node("tools", ejecutar_tools)

    graph.add_edge(START, "agente")
    graph.add_conditional_edges("agente", _debe_ejecutar_tools, {"tools": "tools", END: END})
    graph.add_edge("tools", "agente")

    return graph.compile(checkpointer=checkpointer)
