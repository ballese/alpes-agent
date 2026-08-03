"""[SEMANA 2 — PENDIENTE] Grafo del agente (laboratorios 4 y 5).

Aquí se construye el agente como un grafo de LangGraph. En la primera etapa el
agente es LINEAL: un nodo que invoca al LLM (con las herramientas vinculadas) y
un nodo que ejecuta las herramientas que el modelo pida, conectados en un ciclo
`agente ⇄ herramientas` hasta que el modelo responde sin pedir más herramientas.

La arquitectura interna es DECISIÓN DEL EQUIPO: pueden crear los módulos que
quieran (nodos, estado, prompts, etc.) con los nombres que prefieran. Lo único
que el resto del proyecto espera de este archivo es la función `build_graph`.

Sugerencias de diseño (no obligatorias):
  - Un `State` con la lista de mensajes (reductor `add_messages`).
  - Un nodo "agente" que llame al LLM con `.bind_tools(...)`.
  - Un nodo de ejecución de herramientas (por ejemplo el `ToolNode` de LangGraph).
  - Una arista condicional que decida si volver al agente o terminar.
"""


def build_graph(tools: list | None = None, checkpointer=None):
    """Compila y devuelve el grafo del agente, listo para invocar.

    Parámetros:
        tools:        herramientas disponibles para el agente (locales + MCP).
        checkpointer: memoria de corto plazo (se usa desde la semana 4). Si es
                      None, el grafo funciona igual pero sin persistencia.

    Debe devolver un grafo YA COMPILADO (el resultado de `.compile(...)`).
    """
    raise NotImplementedError(
        "Semana 2: construya el grafo del agente siguiendo los laboratorios 4 y 5."
    )
