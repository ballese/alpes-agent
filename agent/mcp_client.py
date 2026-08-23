"""Cliente MCP del agente (laboratorio 8).

Lanza `mcp_server/server.py` como subproceso (transporte stdio) con el mismo
intérprete que corre el agente (`sys.executable`, así funciona igual dentro
de un venv que en CI) y convierte sus tools en tools de LangChain.

No depende de que la API empresarial ni el RAG estén levantados: eso solo se
necesita cuando el agente invoca una tool, no cuando el servidor arranca y
anuncia su catálogo (`list_tools`), que es lo único que hace `load_mcp_tools`.
"""

import os
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SERVER_SCRIPT = _PROJECT_ROOT / "mcp_server" / "server.py"


def _subprocess_env() -> dict[str, str]:
    """PYTHONPATH explícito para el subproceso del servidor.

    `python mcp_server/server.py` solo agrega a sys.path el directorio del
    script (mcp_server/), no la raíz del repo — sin esto, `server.py` no
    encuentra `cli.config`. Localmente no se nota porque `pip install -e .`
    ya registra el proyecto como paquete global del venv, pero el pipeline
    de CI solo instala requirements.txt.
    """
    raiz = str(_PROJECT_ROOT)
    previo = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{raiz}{os.pathsep}{previo}" if previo else raiz
    return {**os.environ, "PYTHONPATH": pythonpath}


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
                "cwd": str(_PROJECT_ROOT),
                "env": _subprocess_env(),
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
