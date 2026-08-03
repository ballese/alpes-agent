"""Semana 4 — memoria de corto y largo plazo.

Estas pruebas ejercitan SU checkpointer con un grafo mínimo y determinista
definido aquí mismo, sin LLM. Es a propósito: lo que la semana 4 evalúa es la
persistencia, no lo que el modelo responde. Además, invocar el modelo en
GitHub Actions costaría varios minutos por corrida y fallaría cuando la API
empresarial no está disponible en el runner.

La evidencia conversacional (los 3 turnos recordando el contexto) va en la
wiki, como pide la guía.

Correr localmente:  pytest -m semana4
"""

import uuid
from operator import add
from typing import Annotated, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

import contract
from tests.utiles import estado_de, invocar

pytestmark = pytest.mark.semana4


class _Estado(TypedDict):
    pasos: Annotated[list, add]


def _grafo_de_prueba(checkpointer):
    """Grafo trivial de un nodo: solo sirve para escribir y leer checkpoints."""
    grafo = StateGraph(_Estado)
    grafo.add_node("registrar", lambda estado: {"pasos": ["visita"]})
    grafo.add_edge(START, "registrar")
    grafo.add_edge("registrar", END)
    return grafo.compile(checkpointer=checkpointer)


def test_el_checkpointer_se_construye():
    checkpointer = contract.build_checkpointer()
    assert checkpointer is not None, "build_checkpointer() no devolvió nada"
    assert hasattr(checkpointer, "get_tuple"), (
        "Lo devuelto no parece un checkpointer de LangGraph. Si usó "
        "`SqliteSaver.from_conn_string(...)`, recuerde que eso es un context "
        "manager: hay que abrirlo y devolver el checkpointer ya construido."
    )


def test_el_store_se_construye():
    store = contract.build_store()
    assert store is not None, "build_store() no devolvió nada"


def test_un_mismo_thread_acumula_estado():
    config = {"configurable": {"thread_id": f"prueba-{uuid.uuid4()}"}}
    grafo = _grafo_de_prueba(contract.build_checkpointer())

    invocar(grafo, {"pasos": []}, config)
    estado = invocar(grafo, {"pasos": []}, config)

    assert len(estado["pasos"]) >= 2, (
        "Dos invocaciones sobre el mismo thread_id deben acumular estado. "
        f"Se obtuvo: {estado['pasos']}"
    )


def test_threads_distintos_no_comparten_estado():
    grafo = _grafo_de_prueba(contract.build_checkpointer())
    config_a = {"configurable": {"thread_id": f"prueba-a-{uuid.uuid4()}"}}
    config_b = {"configurable": {"thread_id": f"prueba-b-{uuid.uuid4()}"}}

    invocar(grafo, {"pasos": []}, config_a)
    invocar(grafo, {"pasos": []}, config_a)
    estado_b = invocar(grafo, {"pasos": []}, config_b)

    assert len(estado_b["pasos"]) == 1, (
        "Dos thread_id distintos no deben compartir historial: el thread B debería "
        f"tener 1 solo paso y tiene {len(estado_b['pasos'])}"
    )


def test_la_memoria_sobrevive_al_reinicio():
    """El estado debe persistir en disco, no solo en RAM.

    Se escribe con un checkpointer y se lee con otro recién construido, que es
    lo que ocurre cuando el equipo reinicia el CLI. `MemorySaver` falla aquí.
    """
    config = {"configurable": {"thread_id": f"prueba-disco-{uuid.uuid4()}"}}

    invocar(_grafo_de_prueba(contract.build_checkpointer()), {"pasos": []}, config)

    grafo_nuevo = _grafo_de_prueba(contract.build_checkpointer())
    recuperado = estado_de(grafo_nuevo, config)

    assert recuperado.values.get("pasos"), (
        "Una instancia nueva del checkpointer no recuperó el estado. "
        "La memoria debe persistir en disco (SqliteSaver o superior); "
        "MemorySaver no sirve porque se pierde al reiniciar."
    )
