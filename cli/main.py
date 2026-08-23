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

    settings = get_settings()
    ui.banner(settings)

    tools = await _reunir_tools(usar_mcp)
    try:
        graph = build_graph(tools=tools)
    except NotImplementedError:
        ui.error("El agente todavía no está implementado.")
        ui.aviso("Implemente build_graph en agent/graph.py (semana 2) y vuelva a intentarlo.")
        return

    historia: list = []
    turno = 0
    session = PromptSession()

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
            historia = []
            ui.aviso("Conversación reiniciada.")
            continue
        if texto == "/ayuda":
            ui.console.print("[dim]/nueva reinicia la conversación · /salir termina[/dim]")
            continue

        historia.append(HumanMessage(content=texto))
        turno += 1
        # Etiqueta cada turno en LangSmith (laboratorio 9): filtrable por caso/grupo y con
        # un run_name legible en la lista de trazas.
        run_config = {
            "run_id": uuid4(),
            "run_name": f"chat:{settings.caso_negocio}:turno-{turno}",
            "tags": [settings.caso_negocio, f"grupo-{settings.grupo}"],
            "metadata": {"caso": settings.caso_negocio, "grupo": settings.grupo, "turno": turno},
        }
        try:
            async for update in graph.astream(
                {"messages": historia}, config=run_config, stream_mode="updates"
            ):
                for salida_nodo in update.values():
                    for mensaje in salida_nodo.get("messages", []):
                        historia.append(mensaje)
                        if isinstance(mensaje, AIMessage) and mensaje.tool_calls:
                            for llamada in mensaje.tool_calls:
                                ui.tool_llamada(llamada["name"], llamada["args"])
                        elif isinstance(mensaje, ToolMessage):
                            ui.tool_resultado(mensaje.name, str(mensaje.content))
                        elif isinstance(mensaje, AIMessage) and mensaje.content:
                            ui.respuesta_agente(mensaje.content)
        except Exception as exc:  # noqa: BLE001 — el REPL no debe morir por un turno fallido
            ui.error(f"Fallo al invocar el agente: {exc}")
            ui.aviso(
                f"Verifique que Ollama está corriendo ({settings.ollama_base_url}) y que el "
                f"modelo está descargado: ollama pull {settings.ollama_model}"
            )
            historia.pop()

    ui.console.print("[dim]Hasta pronto.[/dim]")


if __name__ == "__main__":
    cli()
