"""Semana 3 — observabilidad con LangSmith.

Verifica dos cosas baratas: que la credencial de LangSmith esté configurada y
funcione, y que el proyecto tenga instrumentación propia (`@traceable`).

El CI NO envía trazas a LangSmith: eso ensuciaría el proyecto del equipo con
corridas de prueba y gastaría cuota. Las trazas reales son el entregable de la
wiki, generadas por ustedes al usar el agente.

Correr localmente:  pytest -m semana3
"""

import os

import pytest

from tests.utiles import nombres_de_decoradores

pytestmark = pytest.mark.semana3

# El SDK acepta ambas familias de nombres; son equivalentes.
_VARIABLES_API_KEY = ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
_VARIABLES_PROYECTO = ("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT")

# Nombres aceptados para el decorador de instrumentación: el de LangSmith y el
# envoltorio propio que el equipo puede escribir sobre él.
DECORADORES_DE_TRAZA = {"traceable", "trazable"}


def _primera(variables):
    for nombre in variables:
        valor = os.getenv(nombre)
        if valor:
            return valor
    return None


def test_api_key_configurada():
    assert _primera(_VARIABLES_API_KEY), (
        "Falta la credencial de LangSmith.\n"
        "En GitHub: Settings → Secrets and variables → Actions → New repository secret,\n"
        "con el nombre LANGCHAIN_API_KEY y la llave entregada por el equipo docente."
    )


def test_proyecto_configurado():
    proyecto = _primera(_VARIABLES_PROYECTO)
    assert proyecto, (
        "Falta el nombre del proyecto de LangSmith.\n"
        "En GitHub: Settings → Secrets and variables → Actions → pestaña Variables →\n"
        "New repository variable, con el nombre LANGCHAIN_PROJECT y el valor\n"
        "misw4412-grupoXY (XY = número de su grupo)."
    )
    assert proyecto.strip() == proyecto and " " not in proyecto, (
        f"El nombre del proyecto no debe tener espacios: {proyecto!r}"
    )


def test_la_credencial_es_valida():
    """Una consulta mínima a LangSmith para confirmar que la llave sirve.

    Si LangSmith no responde (caída o red del runner), la prueba se salta: no
    es un fallo del proyecto del equipo.
    """
    from langsmith import Client

    cliente = Client(api_key=_primera(_VARIABLES_API_KEY))
    try:
        list(cliente.list_projects(limit=1))
    except Exception as exc:  # noqa: BLE001 — se clasifica abajo
        texto = str(exc)
        if any(codigo in texto for codigo in ("401", "403", "Unauthorized", "Forbidden")):
            pytest.fail(
                "LangSmith rechazó la credencial. Verifique que el secret "
                "LANGCHAIN_API_KEY tenga la llave correcta y completa "
                f"(sin espacios ni comillas).\nDetalle: {texto}"
            )
        pytest.skip(f"LangSmith no respondió; no es un problema del proyecto. Detalle: {texto}")


def test_hay_instrumentacion_propia():
    """Debe existir al menos una función propia decorada para trazar.

    Se inspecciona el árbol sintáctico, no el texto: mencionar `@traceable` en
    un comentario o en un docstring no cuenta.
    """
    decoradores = nombres_de_decoradores()
    assert decoradores & DECORADORES_DE_TRAZA, (
        "No se encontró ninguna función decorada con @traceable (laboratorio 9).\n"
        "Instrumente al menos una función propia del proyecto — por ejemplo, la que "
        "prepara el contexto o la que decide la herramienta.\n"
        f"Decoradores encontrados en el proyecto: {sorted(decoradores) or 'ninguno'}"
    )
