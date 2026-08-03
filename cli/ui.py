"""Presentación del CLI con Rich, parametrizable vía cli_design.toml.

Los equipos personalizan colores, banner y símbolo del prompt editando
cli_design.toml en la raíz del repo — sin tocar este código.
"""

import json
import tomllib
from functools import lru_cache
from pathlib import Path

import pyfiglet
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()

DESIGN_PATH = Path(__file__).resolve().parent.parent / "cli_design.toml"

DEFAULTS = {
    "banner": {"title": "Agente MISW4412", "subtitle": "", "font": "small"},
    "colors": {
        "primary": "bright_cyan",
        "accent": "cyan",
        "agent": "green",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
    },
    "prompt": {"symbol": "tú ❯ "},
    "display": {"show_banner": True, "show_tool_calls": True, "agent_title": "agente"},
}


@lru_cache
def design() -> dict:
    """Carga cli_design.toml fusionado sobre los valores por defecto."""
    config = {seccion: dict(valores) for seccion, valores in DEFAULTS.items()}
    if DESIGN_PATH.exists():
        try:
            usuario = tomllib.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            console.print(f"[yellow]⚠ cli_design.toml inválido ({exc}); usando diseño por defecto.[/yellow]")
            return config
        for seccion, valores in usuario.items():
            if seccion in config and isinstance(valores, dict):
                config[seccion].update(valores)
    return config


def prompt_symbol() -> str:
    return design()["prompt"]["symbol"]


def banner(settings) -> None:
    d = design()
    if not d["display"]["show_banner"]:
        return
    colores, textos = d["colors"], d["banner"]
    ascii_art = pyfiglet.figlet_format(textos["title"], font=textos["font"]).rstrip("\n")
    subtitulo = f"\n[{colores['dim']}]{textos['subtitle']}[/{colores['dim']}]" if textos["subtitle"] else ""
    console.print(
        Panel.fit(
            f"[bold {colores['primary']}]{ascii_art}[/bold {colores['primary']}]"
            f"{subtitulo}\n"
            f"Grupo {settings.grupo} · Caso: [bold]{settings.caso_negocio}[/bold] · "
            f"Modelo: [bold]{settings.ollama_model}[/bold]\n"
            f"[{colores['dim']}]/ayuda para comandos · /salir para terminar[/{colores['dim']}]",
            border_style=colores["accent"],
        )
    )


def aviso(texto: str) -> None:
    color = design()["colors"]["warning"]
    console.print(f"[{color}]⚠ {texto}[/{color}]")


def error(texto: str) -> None:
    color = design()["colors"]["error"]
    console.print(f"[bold {color}]✗ {texto}[/bold {color}]")


def tool_llamada(nombre: str, argumentos: dict) -> None:
    d = design()
    if not d["display"]["show_tool_calls"]:
        return
    args = json.dumps(argumentos, ensure_ascii=False)
    console.print(f"  [{d['colors']['dim']}]🔧 {nombre}({args})[/{d['colors']['dim']}]")


def tool_resultado(nombre: str, contenido: str) -> None:
    d = design()
    if not d["display"]["show_tool_calls"]:
        return
    resumen = contenido if len(contenido) <= 200 else contenido[:200] + "…"
    console.print(f"  [{d['colors']['dim']}]   ↳ {resumen}[/{d['colors']['dim']}]")


def respuesta_agente(texto: str) -> None:
    d = design()
    console.print(
        Panel(Markdown(texto), title=d["display"]["agent_title"], border_style=d["colors"]["agent"])
    )
