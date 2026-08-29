"""Contrato del proyecto — único punto de acople con GitHub Actions.

El pipeline del curso NO conoce la arquitectura interna de su agente: solo
importa las funciones de este archivo. Organicen su código como quieran
(`agent/`, `src/`, `core/`, los nombres de módulos y de nodos que prefieran);
lo único obligatorio es que estas funciones existan, se llamen así y devuelvan
lo que dice cada docstring.

Lo habitual es que cada función sea una sola línea que reexporta su propia
implementación. Por ejemplo:

    def build_agent_graph(checkpointer=None):
        from mi_paquete.grafo import construir

        return construir(checkpointer=checkpointer)

Los `import` van DENTRO de cada función, no arriba del archivo. Así, si el
código de una semana todavía no compila, solo fallan las pruebas de esa
semana: las de las demás siguen corriendo.

NO cambien los nombres ni las firmas de las funciones de este archivo: el CI
falla si no las encuentra. Sí pueden (y deben) cambiar lo que hay dentro.
"""


# ── Semana 1 ────────────────────────────────────────────────────────────────
def get_cli():
    """Objeto CLI del proyecto (el grupo `click`/`typer` raíz, sin invocar)."""
    from cli.main import cli

    return cli


def get_settings():
    """Configuración del proyecto.

    Debe exponer al menos los atributos `ollama_model`, `api_base_url` y
    `caso_negocio`, leídos de variables de entorno (nunca escritos a mano en
    el código).
    """
    from cli.config import get_settings as _impl

    return _impl()


# ── Semana 2 ────────────────────────────────────────────────────────────────
def get_tools():
    """Lista de herramientas locales del agente (semana 2: al menos 3).

    Cada herramienta necesita `name` y `description` no vacíos: la descripción
    es lo que el LLM lee para decidir cuándo usarla.
    """
    from agent.tools import get_local_tools

    return get_local_tools()


def build_agent_graph(checkpointer=None):
    """Grafo principal del agente, ya compilado.

    `checkpointer`: si se recibe, se pasa a `.compile()` (se usa desde la
    semana 4). Si es None, el grafo funciona igual pero sin memoria.
    """
    from agent.graph import build_graph

    return build_graph(checkpointer=checkpointer)


async def get_mcp_tools():
    """Herramientas expuestas por SU servidor MCP (semana 2: al menos 1).

    Debe arrancar el servidor y descubrir sus herramientas, sin depender de
    que la API empresarial esté levantada.
    """
    from agent.mcp_client import load_mcp_tools

    return await load_mcp_tools()


# ── Semana 4 ────────────────────────────────────────────────────────────────
def build_checkpointer():
    """Checkpointer de LangGraph con persistencia EN DISCO (memoria corto plazo).

    `MemorySaver` no sirve: la conversación debe sobrevivir a un reinicio.

    Devuelva un checkpointer SÍNCRONO y YA ABIERTO, listo para usar. Con
    SQLite eso se ve así:

        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver(sqlite3.connect("checkpoints.sqlite",
                                           check_same_thread=False))

    Dos errores frecuentes:

    - `SqliteSaver.from_conn_string()` devuelve un context manager, no un
      checkpointer. Hay que abrirlo y devolver lo de adentro.
    - `AsyncSqliteSaver` no se puede construir desde una función síncrona como
      esta (falla con `no running event loop`). Use la versión síncrona: es la
      del laboratorio 11 y la que necesita el CLI.
    """
    """from agent.memory.checkpointer import build_checkpointer as _impl

    return _impl()


def build_store():
    ""Store de memoria de largo plazo (persiste ENTRE conversaciones).""
    from agent.memory.store import build_store as _impl

    return _impl()"""

def build_checkpointer():
    """Checkpointer de LangGraph con persistencia en disco (SqliteSaver)."""
    from agent.memory.checkpointer import build_checkpointer as _impl

    return _impl()


def build_store():
    """Store de memoria de largo plazo (persiste entre conversaciones)."""
    from agent.memory.store import build_store as _impl

    return _impl()


# ── Semana 5 ────────────────────────────────────────────────────────────────
def build_reasoning_graph():
    """Grafo con descomposición explícita de tareas, ya compilado.

    ReAct (laboratorio 13) o Plan-and-Execute (laboratorio 14), a elección del equipo. Debe
    incluir una red de seguridad (`max_iterations` o `max_steps`) que evite
    ciclos infinitos.
    """
    from agent.reasoning.react import build_reasoning_graph as _impl

    return _impl()
