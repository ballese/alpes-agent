"""Helpers de gestión de ventana de contexto.

Reúne en un solo módulo:

- Truncación de payloads grandes de herramientas (RAG, políticas) antes de que
  entren al historial (Item A).
- Trimming intra-turno de la historia del bucle ReAct cuando el presupuesto de
  caracteres se dispara (Item F).
- Constantes de presupuesto compartidas por el grafo principal y el ReAct
  (Items B y F).

Todo es puro y sin dependencias externas — se puede ejercer con pruebas
sencillas sin levantar Postgres ni Ollama.
"""

from __future__ import annotations

from typing import Iterable, List

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# Máximo de caracteres que puede aportar UNA ToolMessage al historial. Los
# payloads mayores se recortan con head + tail y un marcador central. 2000 char
# encaja cómodo en la ventana de qwen2.5:3b y sólo afecta a las respuestas
# realmente grandes (leer_politicas_universidad, buscar_convocatoria).
TOOL_OUTPUT_CAP = 2000

# Presupuesto agregado de caracteres del historial antes de disparar la
# compresión progresiva (Item B) o el trimming del ReAct (Item F). ~8k chars
# ≈ ~2k tokens, con margen para el system prompt.
CONTEXT_CHAR_BUDGET = 8000


def _truncar_tool_content(content: str, cap: int = TOOL_OUTPUT_CAP) -> str:
    """Recorta el contenido de una ToolMessage manteniendo cabeza y cola.

    Devuelve el string original si ya cabe en `cap`. Si no, mantiene los
    primeros 60 % y los últimos 30 % del cap, con un marcador que indica
    cuántos caracteres se eliminaron.
    """
    if not isinstance(content, str):
        content = str(content)
    if len(content) <= cap:
        return content

    cabeza = int(cap * 0.6)
    cola = max(cap - cabeza - 32, 0)  # 32 chars de margen para el marcador
    omitidos = len(content) - cabeza - cola
    return f"{content[:cabeza]}\n…[truncado {omitidos} chars]…\n{content[-cola:]}"


def truncar_tool_messages(messages: Iterable[BaseMessage]) -> List[BaseMessage]:
    """Aplica `_truncar_tool_content` a todas las ToolMessage de una lista.

    Devuelve una NUEVA lista con las ToolMessage grandes reemplazadas por
    copias truncadas; las demás se conservan tal cual. Se usa después de
    invocar el ToolNode/loop de tools, antes de anexar al estado.
    """
    resultado: List[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            nuevo_content = _truncar_tool_content(str(msg.content))
            if nuevo_content != msg.content:
                resultado.append(
                    ToolMessage(
                        content=nuevo_content,
                        name=msg.name,
                        tool_call_id=msg.tool_call_id,
                        id=getattr(msg, "id", None),
                    )
                )
                continue
        resultado.append(msg)
    return resultado


def _chars_totales(messages: Iterable[BaseMessage]) -> int:
    """Suma cruda de caracteres de todos los `content` (para presupuestos)."""
    return sum(len(str(getattr(m, "content", "")) or "") for m in messages)


def trim_react_history(
    messages: List[BaseMessage],
    iterations: int,
    budget: int = CONTEXT_CHAR_BUDGET,
) -> List[BaseMessage]:
    """Recorta la historia del bucle ReAct cuando excede el presupuesto.

    Estrategia pragmática:

    - Si el total de caracteres cabe en `budget`, devuelve la lista intacta.
    - Si no, conserva SIEMPRE:
        * el primer HumanMessage (petición original del usuario),
        * los últimos `2 * max(1, iterations)` mensajes (últimas rondas
          razonar/actuar, que el modelo necesita para continuar),
      y reemplaza el bloque intermedio por un único SystemMessage con la nota
      "Observaciones anteriores omitidas por presupuesto de contexto."

    No toca los objetos originales — devuelve una nueva lista.
    """
    if _chars_totales(messages) <= budget or len(messages) <= 3:
        return list(messages)

    # Petición original: primer HumanMessage; si no lo hay, primer mensaje.
    primer_humano = next(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), 0
    )
    cabeza = messages[: primer_humano + 1]

    ventana = max(1, iterations) * 2
    cola = messages[-ventana:] if ventana < len(messages) else messages[:]

    # Si la cabeza ya está incluida en la cola no dupliques.
    if messages[primer_humano] in cola:
        return [SystemMessage(content=_NOTA_OMITIDA)] + cola

    return cabeza + [SystemMessage(content=_NOTA_OMITIDA)] + cola


_NOTA_OMITIDA = "Observaciones anteriores omitidas por presupuesto de contexto."
