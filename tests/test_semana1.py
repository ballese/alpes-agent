"""Semana 1 — el proyecto arranca y la configuración está sana.

Correr localmente:  pytest -m semana1
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

import contract

pytestmark = pytest.mark.semana1

RAIZ = Path(__file__).resolve().parent.parent


def test_el_cli_arranca():
    resultado = CliRunner().invoke(contract.get_cli(), ["--help"])
    assert resultado.exit_code == 0, (
        "El CLI del proyecto debe responder a --help sin error.\n"
        f"Salida:\n{resultado.output}\n{resultado.exception}"
    )
    assert resultado.output.strip(), "El CLI no imprimió nada con --help"


def test_el_cli_expone_comandos():
    """El CLI debe tener al menos un subcomando. Los nombres los elige el equipo."""
    cli = contract.get_cli()
    comandos = getattr(cli, "commands", None)
    assert comandos, "El CLI debe exponer al menos un subcomando (por ejemplo, `chat`)"


def test_configuracion_disponible():
    settings = contract.get_settings()
    assert settings.ollama_model, "Falta el modelo de Ollama en la configuración"
    assert str(settings.api_base_url).startswith("http"), (
        "`api_base_url` debe ser una URL (viene de la variable de entorno API_BASE_URL)"
    )
    caso = str(settings.caso_negocio or "")
    assert caso.strip(), (
        "Falta `caso_negocio`: identifica el caso asignado a su equipo "
        "(viene de la variable de entorno CASO_NEGOCIO)"
    )


def test_configuracion_por_defecto_sin_env():
    """El proyecto debe funcionar sin `.env` presente.

    En GitHub Actions no existe `.env` (es un archivo de secretos, no se sube).
    Si la configuración no trae valores por defecto, todo el pipeline falla.
    """
    settings = contract.get_settings()
    assert settings is not None


def test_secretos_protegidos():
    gitignore = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [linea.strip() for linea in gitignore], (
        ".env debe estar listado en .gitignore: nunca se suben credenciales al repositorio"
    )
    assert (RAIZ / ".env.example").exists(), (
        "Falta .env.example — es la plantilla que documenta qué variables hacen falta"
    )
