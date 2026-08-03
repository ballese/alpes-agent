"""Semana 2 — herramientas, grafo del agente y servidor MCP.

Se verifica la FORMA del agente, no lo que responde: que las herramientas
estén diseñadas, que el grafo compile y que el servidor MCP arranque y exponga
al menos una herramienta. Nada de esto invoca al LLM.

Correr localmente:  pytest -m semana2
"""

import pytest

import contract
from tests.utiles import nombres_de_nodos

pytestmark = pytest.mark.semana2

# Nombres aceptados para el nodo que EJECUTA herramientas. El equipo elige el
# suyo; esta lista existe para no imponer una arquitectura concreta.
NOMBRES_DE_EJECUCION = {
    "tools", "tool", "tool_node", "toolnode", "herramientas", "herramienta",
    "acciones", "accion", "act", "actuar", "ejecutar", "ejecucion", "executor",
}


def test_hay_al_menos_tres_tools():
    tools = contract.get_tools()
    assert len(tools) >= 3, (
        f"La semana 2 pide al menos 3 herramientas diseñadas; se encontraron {len(tools)}"
    )


def test_cada_tool_tiene_descripcion():
    for tool in contract.get_tools():
        assert getattr(tool, "name", ""), "Toda herramienta necesita un nombre"
        assert getattr(tool, "description", "").strip(), (
            f"La herramienta {tool.name!r} necesita descripción: es el texto que lee "
            "el LLM para decidir cuándo usarla"
        )


def test_el_grafo_compila():
    grafo = contract.build_agent_graph()
    assert grafo is not None, "build_agent_graph() no devolvió un grafo compilado"


def test_el_grafo_tiene_un_nodo_que_ejecuta_herramientas():
    nodos = nombres_de_nodos(contract.build_agent_graph())
    reales = {n for n in nodos if n not in ("__start__", "__end__")}
    assert len(reales) >= 2, (
        f"Se esperaban al menos 2 nodos propios (razonamiento y ejecución); hay: {sorted(reales)}"
    )
    assert reales & NOMBRES_DE_EJECUCION, (
        f"No se reconoce el nodo que ejecuta herramientas. Nodos encontrados: {sorted(reales)}.\n"
        f"Nombre el nodo con alguno de estos: {sorted(NOMBRES_DE_EJECUCION)}"
    )


async def test_el_servidor_mcp_expone_herramientas():
    """Arranca el servidor MCP real como subproceso y descubre sus tools.

    No necesita Ollama ni la API empresarial levantada.
    """
    tools = await contract.get_mcp_tools()
    assert len(tools) >= 1, "El servidor MCP debe exponer al menos una herramienta"
    assert all(getattr(t, "name", "") for t in tools), "Toda herramienta MCP necesita nombre"
