"""[SEMANA 2 — PENDIENTE] Herramientas locales del agente (laboratorio 6).

Las herramientas son las capacidades que el agente puede invocar para consultar
o actuar sobre los sistemas del caso de negocio (por ejemplo, la API empresarial
del centro o la base de conocimiento). Cada herramienta es una función decorada
con `@tool` de LangChain, con una descripción clara: ese texto es lo que el LLM
lee para decidir cuándo usarla.

Diseñen las herramientas que su caso necesite (lean el enunciado). La semana 2
pide al menos 3 herramientas locales, cada una con nombre y descripción.

Las herramientas de ACCIÓN (las que modifican el estado del negocio) se exponen
además a través de su servidor MCP (`mcp_server/server.py`), no aquí.
"""

# from langchain_core.tools import tool
#
# @tool
# def mi_herramienta(argumento: str) -> dict:
#     """Descripción clara: qué hace y cuándo el agente debería usarla."""
#     ...


def get_local_tools() -> list:
    """Lista de herramientas locales del agente (semana 2: al menos 3)."""
    raise NotImplementedError(
        "Semana 2: diseñe e implemente las herramientas locales de su caso "
        "(laboratorio 6). Deben ser al menos 3, cada una con nombre y descripción."
    )
