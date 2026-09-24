"""Semana 5 — Descomposición de tareas: patrón ReAct MANUAL (laboratorio 13).

ReAct = *Reasoning + Acting*. Este grafo NO usa `create_react_agent` ni el
`ToolNode` prebuilt: implementa el ciclo a mano para resolver dos limitaciones
observadas con el modelo local `qwen2.5:3b`:

1. Tras la PRIMERA herramienta, el modelo tiende a narrar en prosa lo que "va a
   hacer" ("ahora necesito consultar tu perfil…") en vez de emitir la siguiente
   `tool_call`; como el mensaje no trae `tool_calls`, la arista condicional
   termina el bucle y solo se ejecutó una tool.
2. No queda ningún registro auditable del razonamiento.

La solución es la del tutorial: un system prompt que FUERZA al modelo a articular
un "Pensamiento:" antes de cada acción y a elegir explícitamente entre *llamar
una herramienta* o *dar la Respuesta final*, más un `reasoning_trace` en el
estado que registra cada paso.

Topología:  START → razonar → (¿tool_calls?) → actuar → razonar → … → END
El ciclo razonar↔actuar es el bucle ReAct. `max_iterations` es la red de
seguridad contra ciclos infinitos: al superarla, `razonar` fuerza el cierre en
lugar de gastar otra llamada al LLM.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.guards.audit_context import set_user_profile
from agent.memory.context import (
    _truncar_tool_content,
    trim_react_history,
)
from agent.tools import get_local_tools
from cli.config import get_settings
from observability.tracing import trazable

# Nombres de tools cuyo resultado sirve como perfil del usuario autenticado.
# Ese perfil viaja al juez en cada peticion de critique/validate.
_PERFIL_TOOLS = frozenset({"consultar_mi_perfil_local", "consultar_mi_perfil"})

# Red de seguridad: nº máximo de pasos de razonamiento antes de forzar el cierre.
# Una petición completa (autenticar → perfil → convocatorias → políticas →
# respuesta) consume ~5-6 pasos; 6 deja aire sin permitir ciclos largos.
MAX_ITERATIONS = 6

# El system prompt es la superficie de ingeniería más importante del patrón:
# obliga a un "Pensamiento:" antes de cada acción y a elegir entre LLAMAR una
# herramienta o dar la "Respuesta final:". Sin esa estructura, qwen2.5:3b narra
# el plan en prosa y el bucle se corta tras la primera tool. Las pistas de
# "cómo leer los resultados" existen porque los modelos pequeños no reconocen
# campos del resultado (el 'token', la lista 'areas_expertise') sin guía
# explícita para encadenar la siguiente herramienta.
SYSTEM_PROMPT_REACT = """Eres el asistente del Centro de Proyectos y Consultoría de la Universidad de los Andes: evalúas convocatorias de investigación y ayudas a conformar equipos. Sigues el patrón ReAct. Responde SIEMPRE en español.

EN CADA RESPUESTA estructuras tu pensamiento así:

1. PENSAMIENTO: empieza con "Pensamiento:" y razona en 1-3 frases sobre:
   - qué pide el usuario (TODAS sus preguntas, no solo la primera),
   - qué datos ya tienes de resultados de herramientas anteriores,
   - qué dato te falta y qué herramienta lo entrega.

2. Luego, EXACTAMENTE una de estas dos opciones:
   a) LLAMA la herramienta que te da el dato que falta (en este mismo mensaje), o
   b) si ya tienes TODO, escribe "Respuesta final:" seguido de la respuesta completa.

REGLAS OBLIGATORIAS:
- SIEMPRE empieza con "Pensamiento:".
- PROHIBIDO narrar lo que vas a hacer sin hacerlo. Si te falta un dato, llama la herramienta AHORA; no escribas "ahora voy a consultar…" sin la llamada.
- Encadena tantas herramientas como haga falta, UNA por turno, hasta cubrir TODAS las preguntas del usuario. Una petición con varias partes (rol, experiencia, convocatorias, riesgo) NO está resuelta hasta responderlas TODAS.
- No adivines ni inventes datos que deben venir de una herramienta.
- No vuelvas a pedir datos que el usuario ya dio (cédula, clave, tema).
- Escribe "Respuesta final:" solo cuando la petición esté cubierta por completo.

CÓMO LEER LOS RESULTADOS (fíjate en los campos):
- autenticarse_centro(numero_identificacion, clave) DEVUELVE 'token' y 'rol'. Copia el valor EXACTO de 'token' y pásalo como argumento 'token' a consultar_mi_perfil (o consultar_mi_perfil_local). El usuario YA queda autenticado; no le pidas la clave otra vez.
- consultar_mi_perfil(token) DEVUELVE 'rol', 'areas_expertise' (lista de temas), 'nivel', 'dedicacion' y 'riesgo' (true/false). Para convocatorias afines, toma los temas de 'areas_expertise' y pásalos como 'query' a buscar_convocatoria. Para "¿hay riesgo?", informa el valor del campo 'riesgo'.
- buscar_convocatoria(query) DEVUELVE 'respuesta' (texto con convocatorias abiertas) y 'fuentes'. Úsalo para decir cuáles encajan con el perfil y por qué.
- leer_politicas_universidad(convocatoria_id) DEVUELVE las políticas de una convocatoria concreta (opcional, para contrastar requisitos).

ACCIONES CON EFECTOS — úsalas solo si el usuario lo pide EXPLÍCITAMENTE:
- crear_solicitud: registrar una postulación.
- asignar_convocatoria: asignar un equipo (solo si el 'rol' es 'directivo').
- escalar: derivar a decisión humana. Que el usuario pida "revisar si hay riesgo" NO es escalar: es informar el campo 'riesgo' del perfil.

Si la pregunta no es del dominio del Centro de Proyectos, responde directo con "Respuesta final:" y sin herramientas."""


class ReActState(TypedDict):
    """Estado del bucle ReAct manual.

    messages:        historia completa de la conversación (el reducer
                     add_messages fusiona los mensajes nuevos con los previos).
    reasoning_trace: lista de "Pensamientos" y observaciones que cada nodo
                     añade — el artefacto ReAct, inspeccionable al terminar.
    iterations:      nº de pasos de razonamiento ya consumidos.
    max_iterations:  tope de seguridad; se puede sembrar desde el CLI y, si no,
                     cae al valor por defecto del grafo.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    reasoning_trace: Annotated[list[str], operator.add]
    iterations: int
    max_iterations: int


def _ejecutar_tool(tool, args: dict):
    """Invoca una tool sea síncrona o asíncrona (las de MCP lo son) desde un
    contexto síncrono, sin chocar con el event loop del CLI.
    """
    try:
        return tool.invoke(args)
    except NotImplementedError:
        # Tool async-only (FastMCP): corre la corrutina en un hilo aislado.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, tool.ainvoke(args)).result()


def build_reasoning_graph(
    tools: list | None = None,
    max_iterations: int = MAX_ITERATIONS,
    checkpointer=None,
):
    """Compila el grafo ReAct manual (razonar↔actuar) con red de seguridad.

    tools:            herramientas disponibles; por defecto, las locales.
    max_iterations:   tope de pasos de razonamiento (red de seguridad). El CLI
                      puede además sembrarlo en el estado inicial.
    checkpointer:     opcional; si se pasa, habilita memoria de la sesión.
    """
    tools = tools if tools is not None else get_local_tools()
    tools_map = {t.name: t for t in tools}  # dispatcher O(1) nombre -> tool

    settings = get_settings()
    model = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    ).bind_tools(tools)

    @trazable(name="nodo_razonar", run_type="chain", tags=["react", "reason"])
    def razonar(state: ReActState) -> dict:
        """Paso 'Pensamiento': el modelo razona y decide la siguiente acción.

        Antepone el system prompt ReAct a toda la historia, invoca al LLM y
        registra el pensamiento textual en `reasoning_trace`. Si se superó el
        tope de iteraciones, emite un cierre forzado en lugar de llamar al LLM.
        """
        paso = state.get("iterations", 0) + 1
        tope = state.get("max_iterations") or max_iterations

        # Red de seguridad: no gastes otra llamada al LLM si ya superaste el tope.
        if paso > tope:
            forzado = AIMessage(
                content=(
                    "Respuesta final: alcancé el máximo de pasos de razonamiento. "
                    "Te comparto lo que pude reunir hasta ahora."
                )
            )
            return {
                "messages": [forzado],
                "reasoning_trace": [
                    f"[Paso {paso}] CIERRE FORZADO — tope de iteraciones"
                ],
                "iterations": paso,
            }

        # Item F: recorta la historia intra-turno cuando el presupuesto de
        # caracteres se dispara — conservamos la petición original y la última
        # ventana razonar/actuar; el bloque intermedio se reemplaza por una
        # nota de omisión. Evita que un bucle con RAG largo llene la ventana.
        contexto = [SystemMessage(content=SYSTEM_PROMPT_REACT)] + trim_react_history(
            list(state["messages"]), paso
        )
        respuesta = model.invoke(contexto)

        # El pensamiento vive en .content; las tool_calls (si las hay) en
        # .tool_calls y las detecta la arista condicional para enrutar a actuar.
        contenido = respuesta.content
        pensamiento = (
            contenido if isinstance(contenido, str) else str(contenido)
        ).strip()
        entrada_traza = (
            f"[Paso {paso}] {pensamiento}"
            if pensamiento
            else f"[Paso {paso}] (tool call sin pensamiento explícito)"
        )

        return {
            "messages": [respuesta],
            "reasoning_trace": [entrada_traza],
            "iterations": paso,
        }

    @trazable(name="nodo_actuar", run_type="chain", tags=["react", "act"])
    def actuar(state: ReActState) -> dict:
        """Paso 'Acción': ejecuta TODAS las tool_calls del último AIMessage.

        Resuelve cada tool por nombre en `tools_map`, la invoca y envuelve el
        resultado en un ToolMessage con su `tool_call_id` para que el modelo
        empareje cada observación con su petición. Añade una línea legible por
        cada llamada a `reasoning_trace`.
        """
        ultimo = state["messages"][-1]
        mensajes_tool: list[ToolMessage] = []
        observaciones: list[str] = []

        for llamada in ultimo.tool_calls:
            tool = tools_map.get(llamada["name"])
            if tool is None:
                resultado = (
                    f"Error: la herramienta '{llamada['name']}' no existe. "
                    f"Disponibles: {list(tools_map)}"
                )
            else:
                try:
                    resultado = _ejecutar_tool(tool, llamada["args"])
                except Exception as exc:  # noqa: BLE001 — el error vuelve como observación
                    resultado = f"Error ejecutando {llamada['name']}: {exc}"

            mensajes_tool.append(
                ToolMessage(
                    # Item A: recorta payloads grandes (leer_politicas,
                    # buscar_convocatoria) antes de que entren al historial;
                    # las respuestas cortas pasan intactas.
                    content=_truncar_tool_content(str(resultado)),
                    name=llamada["name"],
                    tool_call_id=llamada["id"],
                )
            )
            observaciones.append(
                f"  ↳ {llamada['name']}({llamada['args']}) → {resultado}"
            )

            # Perfil del usuario autenticado → contexto de auditoria del juez.
            # Solo si la tool fue de perfil y el resultado no trae 'error'.
            if (
                llamada["name"] in _PERFIL_TOOLS
                and isinstance(resultado, dict)
                and "error" not in resultado
            ):
                set_user_profile(resultado)

        return {"messages": mensajes_tool, "reasoning_trace": observaciones}

    def _continuar(state: ReActState) -> Literal["actuar", "__end__"]:
        """Router de dos pasos: si el último AIMessage pidió herramientas, sigue
        a `actuar`; si no, el modelo dio su respuesta final y el grafo termina.
        """
        ultimo = state["messages"][-1] if state.get("messages") else None
        if isinstance(ultimo, AIMessage) and ultimo.tool_calls:
            return "actuar"
        return "__end__"

    grafo = StateGraph(ReActState)
    grafo.add_node("razonar", razonar)
    grafo.add_node("actuar", actuar)

    grafo.add_edge(START, "razonar")
    grafo.add_conditional_edges(
        "razonar", _continuar, {"actuar": "actuar", "__end__": END}
    )
    grafo.add_edge(
        "actuar", "razonar"
    )  # la observación alimenta el próximo pensamiento

    return grafo.compile(checkpointer=checkpointer)
