"""Utilidades compartidas por las pruebas del curso.

Estas pruebas verifican que el proyecto AVANZA cada semana: que las piezas de
la semana existen, se construyen y tienen la forma correcta. No evalúan la
calidad de las respuestas del agente — eso se sustenta en los videos y en las
entregas 1, 2 y 3.

Por eso ninguna prueba invoca al LLM, ni a la API empresarial, ni descarga
modelos: correrían durante minutos en GitHub Actions, gastarían la cuota del
curso y fallarían por causas ajenas a su implementación.
"""

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Carpetas que nunca contienen código del equipo.
_IGNORADAS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "tests",
    "notebooks", "node_modules", ".langgraph_api", "build", "dist",
}


def archivos_del_proyecto():
    """Todos los .py escritos por el equipo (excluye entornos y pruebas)."""
    for ruta in RAIZ.rglob("*.py"):
        if any(parte in _IGNORADAS or parte.endswith(".egg-info") for parte in ruta.parts):
            continue
        yield ruta


def _arboles():
    for ruta in archivos_del_proyecto():
        try:
            yield ruta, ast.parse(ruta.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue  # un archivo roto no es asunto de esta prueba


def nombres_de_decoradores():
    """Decoradores realmente aplicados a funciones del proyecto.

    Se usa AST y no `grep` a propósito: buscar texto encuentra la palabra en
    comentarios y docstrings, y daría por bueno un proyecto sin instrumentar.
    """
    encontrados = set()
    for _, arbol in _arboles():
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in nodo.decorator_list:
                objetivo = deco.func if isinstance(deco, ast.Call) else deco
                if isinstance(objetivo, ast.Name):
                    encontrados.add(objetivo.id)
                elif isinstance(objetivo, ast.Attribute):
                    encontrados.add(objetivo.attr)
    return encontrados


def identificadores_del_proyecto():
    """Identificadores usados en el CÓDIGO (variables, parámetros, atributos).

    No incluye texto de docstrings ni de comentarios, para que la prueba no se
    pueda aprobar escribiendo el nombre en un comentario.
    """
    encontrados = set()
    for _, arbol in _arboles():
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Name):
                encontrados.add(nodo.id)
            elif isinstance(nodo, ast.arg):
                encontrados.add(nodo.arg)
            elif isinstance(nodo, ast.Attribute):
                encontrados.add(nodo.attr)
            elif isinstance(nodo, ast.keyword) and nodo.arg:
                encontrados.add(nodo.arg)
    return encontrados


def nombres_de_nodos(grafo_compilado):
    """Nombres de los nodos de un grafo de LangGraph ya compilado, en minúscula."""
    return {str(n).lower() for n in grafo_compilado.get_graph().nodes}


def invocar(grafo, entrada, config):
    """Invoca un grafo compilado, funcione su checkpointer en sync o en async.

    `SqliteSaver` solo soporta el camino síncrono y `AsyncSqliteSaver` solo el
    asíncrono; el equipo puede haber elegido cualquiera de los dos.
    """
    try:
        return grafo.invoke(entrada, config)
    except NotImplementedError:
        import asyncio

        return asyncio.run(grafo.ainvoke(entrada, config))


def estado_de(grafo, config):
    """Lee el estado persistido de un thread, en sync o en async."""
    try:
        return grafo.get_state(config)
    except NotImplementedError:
        import asyncio

        return asyncio.run(grafo.aget_state(config))
