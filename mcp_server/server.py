"""[SEMANA 2 — PENDIENTE] Servidor MCP del equipo (laboratorio 7).

Este servidor expone las herramientas de ACCIÓN del agente (las que modifican el
estado del negocio: registrar, escalar, crear, etc.) mediante el Model Context
Protocol. Corre como proceso independiente (transporte stdio); su agente lo
consume a través del cliente MCP (`agent/mcp_client.py`).

Abajo hay un servidor MÍNIMO que ya funciona, con una herramienta de ejemplo
(`ping`) para que verifiquen el transporte:

    python mcp_server/server.py        # lo arranca en modo stdio (para el cliente)

REEMPLACEN la herramienta de ejemplo por las herramientas de acción de SU caso
de negocio (lean el enunciado). La semana 2 pide que el servidor exponga al
menos una herramienta propia.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("acciones-del-agente")


@mcp.tool()
def ping() -> str:
    """Herramienta de EJEMPLO. Confirma que el servidor MCP responde.

    Bórrela y ponga en su lugar las herramientas de acción de su caso.
    """
    return "pong"


if __name__ == "__main__":
    mcp.run(transport="stdio")
