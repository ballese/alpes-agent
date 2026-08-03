"""[SEMANA 2 — PENDIENTE] Cliente MCP del agente (laboratorio 8).

El cliente MCP lanza SU servidor MCP (`mcp_server/server.py`) como subproceso
(transporte stdio) y convierte las herramientas que expone en tools de LangChain,
para que el agente las use igual que las locales.

Implementen `load_mcp_tools()` conectándose a su servidor. `load_mcp_tools_safe()`
ya está lista: envuelve la anterior para que el CLI no se caiga si el servidor
todavía no existe o no arranca (degrada a solo herramientas locales).
"""


async def load_mcp_tools() -> list:
    """Descubre y devuelve las herramientas expuestas por su servidor MCP.

    Debe arrancar el servidor y listar sus tools, sin depender de que la API
    empresarial esté levantada (semana 2: al menos 1 herramienta).
    """
    raise NotImplementedError(
        "Semana 2: conecte el cliente MCP a su servidor siguiendo el laboratorio 8."
    )


async def load_mcp_tools_safe() -> tuple[list, str | None]:
    """Variante tolerante para el CLI: retorna (tools, error).

    Si el cliente MCP todavía no está implementado o el servidor no arranca,
    retorna ([], mensaje) y el CLI sigue funcionando solo con las tools locales.
    """
    try:
        return await load_mcp_tools(), None
    except Exception as exc:  # noqa: BLE001 — cualquier fallo degrada, no rompe
        return [], str(exc)
