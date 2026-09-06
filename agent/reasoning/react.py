"""Semana 5 — Descomposición de tareas con el patrón ReAct (laboratorio 13).

ReAct = *Reasoning + Acting*: el agente alterna un paso de RAZONAMIENTO (decide,
con el modelo local, qué hacer y por qué) con un paso de ACCIÓN (ejecuta una
herramienta y observa el resultado). El ciclo se repite hasta que el modelo
responde sin pedir más herramientas.

A diferencia del grafo de la semana 2 (que ya tiene forma de bucle
razonar↔herramientas), aquí el bucle es EXPLÍCITO y observable: nodos `razonar`
y `actuar`, un contador de iteraciones en el estado y una red de seguridad
`max_iterations` que corta cualquier ciclo infinito.

`build_reasoning_graph()` solo compila: no se conecta a nada. Las herramientas
por defecto son las locales (`get_local_tools`), que incluyen autenticación,
consulta de perfil y las acciones del Centro.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.tools import get_local_tools
from cli.config import get_settings
from observability.tracing import trazable

# Red de seguridad: nº máximo de vueltas razonar→actuar antes de rendirse.
MAX_ITERATIONS = 6

SYSTEM_PROMPT_REACT = (
    "Responde SIEMPRE en español. Eres el asistente del Centro de Proyectos y "
    "Consultoría de la Universidad de los Andes. Evalúas convocatorias de "
    "investigación y ayudas a conformar equipos.\n\n"
    "Trabajas con el patrón ReAct: razonas en una frase breve qué necesitas y "
    "por qué, y a continuación llamas la herramienta que corresponda. El grafo "
    "la ejecuta y te devuelve el resultado para que sigas.\n"
    "REGLAS DE OPERACIÓN (obligatorias):\n"
    "- ENCADENA por tu cuenta todas las herramientas necesarias, una tras otra, "
    "hasta cumplir el objetivo del usuario. NO te detengas a pedir permiso ni "
    "confirmación entre pasos.\n"
    "- NO vuelvas a preguntar por datos que el usuario YA dio en su mensaje "
    "(cédula, clave, tema): extráelos y úsalos directamente.\n"
    "- Solo te diriges al usuario cuando (a) ya tienes la respuesta final, o "
    "(b) falta un dato imprescindible que el usuario nunca entregó.\n"
    "- No inventes datos que deben venir de una herramienta.\n\n"
    "Flujo para 'ver convocatorias que se ajustan a mi perfil':\n"
    "1. autenticarse_centro(numero_identificacion, clave) -> devuelve 'token' y 'rol'.\n"
    "2. consultar_mi_perfil_local(token=<el valor EXACTO de 'token' del paso 1>) "
    "-> devuelve areas_expertise, nivel, dedicación.\n"
    "3. buscar_convocatoria(query=<los temas de areas_expertise del perfil>) "
    "-> convocatorias abiertas.\n"
    "4. (opcional) leer_politicas_universidad(convocatoria_id) por cada candidata.\n"
    "5. Responde qué convocatorias encajan con el perfil y por qué.\n\n"
    "Otras reglas del caso:\n"
    "- Para postular a alguien: revisa convocatoria, políticas y perfil; si no "
    "hay riesgo ni ambigüedad usa crear_solicitud; si hay riesgo reputacional, "
    "sector restringido o el caso necesita juicio humano, usa escalar.\n"
    "- Solo un directivo puede usar asignar_convocatoria."
)


class ReActState(TypedDict):
    """Estado del bucle ReAct: hilo de mensajes + contador de iteraciones."""

    messages: Annotated[list[BaseMessage], add_messages]
    iterations: int


def build_reasoning_graph(
    tools: list | None = None,
    max_iterations: int = MAX_ITERATIONS,
    checkpointer=None,
):
    """Compila el grafo ReAct (razonar↔actuar) con red de seguridad.

    tools:            herramientas disponibles; por defecto, las locales.
    max_iterations:   tope de vueltas del bucle antes de terminar (red de
                      seguridad contra ciclos infinitos).
    checkpointer:     opcional; si se pasa, habilita memoria de la sesión.
    """
    tools = tools if tools is not None else get_local_tools()

    settings = get_settings()
    model = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    ).bind_tools(tools)

    tool_node = ToolNode(tools)

    @trazable(name="nodo_razonar", run_type="chain", tags=["react", "reason"])
    def razonar(state: ReActState) -> dict:
        """Paso de razonamiento: el modelo decide la siguiente acción (o responde)."""
        context = [SystemMessage(content=SYSTEM_PROMPT_REACT)] + list(state["messages"])
        respuesta = model.invoke(context)
        return {
            "messages": [respuesta],
            "iterations": state.get("iterations", 0) + 1,
        }

    @trazable(name="nodo_actuar", run_type="chain", tags=["react", "act"])
    def actuar(state: ReActState) -> dict:
        """Paso de acción: ejecuta las herramientas pedidas y devuelve la observación."""
        return tool_node.invoke(state)

    def _continuar(state: ReActState) -> Literal["actuar", "__end__"]:
        """Sigue actuando solo si el modelo pidió herramientas y queda presupuesto."""
        ultimo = state["messages"][-1] if state.get("messages") else None
        quiere_actuar = isinstance(ultimo, AIMessage) and bool(ultimo.tool_calls)
        if quiere_actuar and state.get("iterations", 0) < max_iterations:
            return "actuar"
        return "__end__"

    grafo = StateGraph(ReActState)
    grafo.add_node("razonar", razonar)
    grafo.add_node("actuar", actuar)

    grafo.add_edge(START, "razonar")
    grafo.add_conditional_edges(
        "razonar", _continuar, {"actuar": "actuar", "__end__": END}
    )
    grafo.add_edge("actuar", "razonar")

    return grafo.compile(checkpointer=checkpointer)
