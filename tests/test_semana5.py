"""Semana 5 — descomposición explícita de tareas (ReAct o Plan-and-Execute).

Se verifica que el grafo de razonamiento exista, compile y tenga nodos
reconocibles del patrón elegido, y que haya una red de seguridad contra ciclos
infinitos. No se ejecuta el razonamiento: eso requiere LLM.

Correr localmente:  pytest -m semana5
"""

import pytest

import contract
from tests.utiles import identificadores_del_proyecto, nombres_de_nodos

pytestmark = pytest.mark.semana5

NOMBRES_REACT = {
    "reason", "reasoning", "think", "thought", "act", "action",
    "razonar", "razonamiento", "pensar", "actuar", "accion",
}
NOMBRES_PLAN = {
    "planner", "plan", "executor", "execute", "replanner", "replan",
    "planificador", "planificar", "ejecutor", "ejecutar", "replanificador",
}
REDES_DE_SEGURIDAD = {
    "max_iterations", "max_steps", "max_iteraciones", "max_pasos",
    "limite_iteraciones", "limite_pasos", "recursion_limit",
}


def test_el_grafo_de_razonamiento_compila():
    grafo = contract.build_reasoning_graph()
    assert grafo is not None, "build_reasoning_graph() no devolvió un grafo compilado"


def test_tiene_nodos_del_patron_elegido():
    nodos = nombres_de_nodos(contract.build_reasoning_graph())
    reales = {n for n in nodos if n not in ("__start__", "__end__")}
    assert reales & (NOMBRES_REACT | NOMBRES_PLAN), (
        f"No se reconocen nodos de ReAct ni de Plan-and-Execute. Nodos: {sorted(reales)}.\n"
        f"Use nombres como {sorted(NOMBRES_REACT)} (ReAct) "
        f"o {sorted(NOMBRES_PLAN)} (Plan-and-Execute)."
    )


def test_tiene_red_de_seguridad():
    """Todo grafo cíclico necesita un límite explícito de iteraciones o pasos.

    Se busca el identificador en el código (AST), no en el texto: escribirlo en
    un comentario o en un docstring no cuenta.
    """
    identificadores = identificadores_del_proyecto()
    assert identificadores & REDES_DE_SEGURIDAD, (
        "No se encontró una red de seguridad en el código.\n"
        "Un grafo con ciclos debe tener un límite explícito de iteraciones o de "
        f"pasos. Use alguno de estos nombres: {sorted(REDES_DE_SEGURIDAD)}."
    )
