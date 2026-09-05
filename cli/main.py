"""CLI del agente MISW4412.

Comandos:
    agente chat          — conversación interactiva con el agente
    agente config        — muestra la configuración vigente
    agente herramientas  — lista las tools disponibles (locales + MCP)
    agente probar-tool   — invoca una tool directamente, sin pasar por el LLM
    agente version
"""

import asyncio
import json
from uuid import uuid4
from importlib.metadata import PackageNotFoundError, version as pkg_version

import click
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from cli import ui
from cli.config import get_settings


@click.group()
def cli():
    """Agente del curso MISW4412 — Fundamentos de Agentes de IA."""


@cli.command()
def version():
    """Versión instalada del proyecto."""
    try:
        click.echo(pkg_version("misw4412-agente"))
    except PackageNotFoundError:
        click.echo("0.1.0 (sin instalar; use pip install -e .)")


@cli.command()
def config():
    """Configuración vigente del agente."""
    settings = get_settings()
    click.echo(f"modelo Ollama    : {settings.ollama_model}")
    click.echo(f"Ollama URL       : {settings.ollama_base_url}")
    click.echo(f"API empresarial  : {settings.api_base_url}")
    click.echo(f"Base de memoria  : {settings.database_url}")
    click.echo(f"RAG (conocimiento): {settings.rag_base_url} · colección {settings.rag_collection}")
    click.echo(f"caso de negocio  : {settings.caso_negocio}")
    click.echo(f"grupo            : {settings.grupo}")
    click.echo(f"LangSmith activo : {settings.langsmith_tracing}")


async def _reunir_tools(usar_mcp: bool) -> list:
    from agent.mcp_client import load_mcp_tools_safe
    from agent.tools import get_local_tools

    try:
        tools = get_local_tools()
    except NotImplementedError:
        # Todavía no hay herramientas locales (semana 2). El CLI sigue arrancando.
        tools = []
    if usar_mcp:
        mcp_tools, error_mcp = await load_mcp_tools_safe()
        if error_mcp:
            ui.aviso(f"Servidor MCP no disponible ({error_mcp}). Continuando solo con tools locales.")
        tools = tools + mcp_tools
    return tools


@cli.command()
@click.option("--sin-mcp", is_flag=True, help="No conectar el servidor MCP (solo tools locales).")
def herramientas(sin_mcp: bool):
    """Lista las herramientas que el agente tiene disponibles."""
    tools = asyncio.run(_reunir_tools(usar_mcp=not sin_mcp))
    if not tools:
        ui.aviso("Todavía no hay herramientas. Impleméntelas en la semana 2 (agent/tools.py y mcp_server/server.py).")
        return
    for tool in tools:
        descripcion = (tool.description or "").split("\n")[0]
        click.echo(f"- {tool.name}: {descripcion}")


@cli.command(name="probar-tool")
@click.argument("nombre")
@click.argument("argumentos", default="{}")
@click.option("--sin-mcp", is_flag=True, help="Buscar solo entre las tools locales.")
def probar_tool(nombre: str, argumentos: str, sin_mcp: bool):
    """Invoca una tool directamente (sin LLM), útil para probar el acceso a la API.

    Ejemplo: agente probar-tool consultar_contacto '{"contacto_id": "CTO-001"}'
    """

    async def _run():
        tools = await _reunir_tools(usar_mcp=not sin_mcp)
        tool = next((t for t in tools if t.name == nombre), None)
        if tool is None:
            disponibles = ", ".join(t.name for t in tools)
            raise click.ClickException(f"Tool '{nombre}' no existe. Disponibles: {disponibles}")
        try:
            args = json.loads(argumentos)
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Argumentos inválidos (deben ser JSON): {exc}")
        resultado = await tool.ainvoke(args)
        click.echo(resultado if isinstance(resultado, str) else json.dumps(resultado, indent=2, ensure_ascii=False))

    asyncio.run(_run())


@cli.command()
@click.option("--sin-mcp", is_flag=True, help="No conectar el servidor MCP (solo tools locales).")
def chat(sin_mcp: bool):
    """Conversación interactiva con el agente."""
    asyncio.run(_chat(usar_mcp=not sin_mcp))


async def _chat(usar_mcp: bool):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout

    from agent.graph import build_graph
    from agent.memory.checkpointer import build_checkpointer
    from agent.memory.store import SINGLE_USER_ID, build_store

    settings = get_settings()
    ui.banner(settings)

    tools = await _reunir_tools(usar_mcp)
    checkpointer = build_checkpointer()
    store = build_store()

    try:
        graph = build_graph(tools=tools, checkpointer=checkpointer, store=store)
    except NotImplementedError:
        ui.error("El agente todavía no está implementado.")
        ui.aviso("Implemente build_graph en agent/graph.py y vuelva a intentarlo.")
        return

    session_id = str(uuid4())[:8]
    thread_id = f"centro-{session_id}"
    user_id = SINGLE_USER_ID
    turno = 0
    session = PromptSession()

    ui.aviso(f"Sesión iniciada | Thread ID: {thread_id} | Usuario: {user_id}")

    while True:
        try:
            with patch_stdout():
                texto = (await session.prompt_async(ui.prompt_symbol())).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not texto:
            continue
        if texto in ("/salir", "/exit"):
            break
        if texto == "/nueva":
            session_id = str(uuid4())[:8]
            thread_id = f"centro-{session_id}"
            turno = 0
            ui.aviso(f"Nueva sesión iniciada | Nuevo Thread ID: {thread_id} (Memoria de largo plazo conservada).")
            continue
        if texto == "/ayuda":
            ui.console.print("[dim]/nueva reinicia la sesión (nuevo thread_id) · /salir termina[/dim]")
            continue

        turno += 1
        # Configuración con thread_id requerido por el checkpointer y etiquetas de LangSmith
        run_config = {
            "configurable": {"thread_id": thread_id},
            "run_id": uuid4(),
            "run_name": f"chat:{settings.caso_negocio}:turno-{turno}",
            "tags": [settings.caso_negocio, f"grupo-{settings.grupo}"],
            "metadata": {
                "caso": settings.caso_negocio,
                "grupo": settings.grupo,
                "turno": turno,
                "user_id": user_id,
            },
        }

        try:
            input_state = {
                "messages": [HumanMessage(content=texto)],
                "user_id": user_id,
            }
            for update in graph.stream(
                input_state, config=run_config, stream_mode="updates"
            ):
                if not isinstance(update, dict):
                    continue
                for salida_nodo in update.values():
                    if not isinstance(salida_nodo, dict):
                        continue
                    for mensaje in salida_nodo.get("messages", []):
                        if isinstance(mensaje, AIMessage) and mensaje.tool_calls:
                            for llamada in mensaje.tool_calls:
                                ui.tool_llamada(llamada["name"], llamada["args"])
                        elif isinstance(mensaje, ToolMessage):
                            ui.tool_resultado(mensaje.name, str(mensaje.content))
                        elif isinstance(mensaje, AIMessage) and mensaje.content:
                            ui.respuesta_agente(mensaje.content)
        except Exception as exc:  # noqa: BLE001
            ui.error(f"Fallo al invocar el agente: {exc}")
            ui.aviso(
                f"Verifique que Ollama está corriendo ({settings.ollama_base_url}) y que el "
                f"modelo está descargado: ollama pull {settings.ollama_model}"
            )

    ui.console.print("[dim]Hasta pronto.[/dim]")


@cli.command()
@click.argument("mensaje")
@click.option("--sin-mcp", is_flag=True, help="Solo tools locales (sin el servidor MCP).")
@click.option("--max-iteraciones", default=6, show_default=True,
              help="Red de seguridad del bucle ReAct (semana 5).")
def razonar(mensaje: str, sin_mcp: bool, max_iteraciones: int):
    """Ejecuta el grafo ReAct de la semana 5 sobre un mensaje y muestra la traza razonar↔actuar.

    A diferencia de `chat` (que usa el grafo de memoria de la semana 2/4), este
    comando invoca `build_reasoning_graph` con TODAS las tools (locales + MCP) y
    imprime cada paso del ciclo y el nº de iteraciones consumidas.

    Ejemplo: agente razonar "Mi cédula es 1020340003 y mi clave es 0003, muéstrame convocatorias para mi perfil"
    """
    asyncio.run(_razonar(mensaje, usar_mcp=not sin_mcp, max_iteraciones=max_iteraciones))


async def _razonar(mensaje: str, usar_mcp: bool, max_iteraciones: int):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from agent.reasoning.react import build_reasoning_graph

    settings = get_settings()
    tools = await _reunir_tools(usar_mcp)
    ui.aviso(f"Tools disponibles: {', '.join(t.name for t in tools) or '(ninguna)'}")

    grafo = build_reasoning_graph(tools=tools, max_iterations=max_iteraciones)
    entrada = {"messages": [HumanMessage(content=mensaje)], "iterations": 0}
    config = {
        "configurable": {"thread_id": f"razonar-{uuid4().hex[:8]}"},
        "recursion_limit": 2 * max_iteraciones + 4,
    }

    iteraciones = 0
    try:
        for update in grafo.stream(entrada, config=config, stream_mode="updates"):
            for _nodo, salida in update.items():
                salida = salida or {}
                if "iterations" in salida:
                    iteraciones = salida["iterations"]
                for msg in salida.get("messages", []):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for llamada in msg.tool_calls:
                            ui.tool_llamada(llamada["name"], llamada["args"])
                    elif isinstance(msg, ToolMessage):
                        ui.tool_resultado(msg.name, str(msg.content))
                    elif isinstance(msg, AIMessage) and msg.content:
                        ui.respuesta_agente(msg.content)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"Fallo en el grafo de razonamiento: {exc}")
        ui.aviso(
            f"Verifique que Ollama está corriendo ({settings.ollama_base_url}) y que "
            f"el modelo está descargado: ollama pull {settings.ollama_model}"
        )
        return

    ui.aviso(f"Iteraciones ReAct: {iteraciones} / {max_iteraciones}")


if __name__ == "__main__":
    cli()
