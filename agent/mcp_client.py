"""Cliente MCP del agente (laboratorio 8).

Lanza `mcp_server/server.py` como subproceso (transporte stdio) con el mismo
intérprete que corre el agente (`sys.executable`, así funciona igual dentro
de un venv que en CI) y convierte sus tools en tools de LangChain.

No depende de que la API empresarial ni el RAG estén levantados: eso solo se
necesita cuando el agente invoca una tool, no cuando el servidor arranca y
anuncia su catálogo (`list_tools`), que es lo único que hace `load_mcp_tools`.
"""

import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

_SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"


async def load_mcp_tools() -> list:
    """Descubre y devuelve las herramientas expuestas por su servidor MCP.

    Arranca el servidor por stdio y lista sus tools (semana 2: al menos 1).
    """
    client = MultiServerMCPClient(
        {
            "centro-proyectos": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(_SERVER_SCRIPT)],
            }
        }
    )
    return await client.get_tools()


async def load_mcp_tools_safe() -> tuple[list, str | None]:
    """Variante tolerante para el CLI: retorna (tools, error).

    Si el cliente MCP todavía no está implementado o el servidor no arranca,
    retorna ([], mensaje) y el CLI sigue funcionando solo con las tools locales.
    """
    try:
        return await load_mcp_tools(), None
    except Exception as exc:  # noqa: BLE001 — cualquier fallo degrada, no rompe
        return [], str(exc)
