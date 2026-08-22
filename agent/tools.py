"""Herramientas locales del agente (laboratorio 6) — Centro de Proyectos.

Estas son las tools de ACCIÓN + autenticación: modifican el estado del
negocio (crear_solicitud, asignar_convocatoria) o generan el token que las
demás tools necesitan (autenticarse_centro). Las tools de SOLO LECTURA
(convocatorias, políticas, personal, historial) viven en el servidor MCP
(mcp_server/server.py), no aquí.

El flujo de autenticación es el que ya expone la API empresarial (sección 4
de su README): GET /personal/existe/{cedula} (sin token), luego
POST /auth/login con {numero_identificacion, clave} (clave de 4 dígitos)
devuelve un bearer token. El agente pide primero cédula y clave (ver el
system prompt de agent/graph.py) y usa autenticarse_centro para
obtenerlo; ese token es el que hay que pasarle luego a las tools MCP que lo
necesiten (consultar_perfil_personal, consultar_historial_participaciones).
"""

import httpx
from langchain_core.tools import tool

from cli.config import get_settings
from observability.tracing import trazable


def _centro_url(path: str) -> str:
    return f"{get_settings().api_base_url}/centro-proyectos{path}"


@tool
@trazable(name="autenticarse_centro")
def autenticarse_centro(numero_identificacion: str, clave: str) -> dict:
    """Autentica a un miembro del Centro de Proyectos con su cédula y su clave
    de 4 dígitos. Úsala ANTES de crear_solicitud o de consultar tools que
    requieran token (consultar_perfil_personal, consultar_historial_participaciones).
    Retorna el bearer token y el rol (personal | directivo), que determina qué
    puede hacer el usuario (por ejemplo, solo un directivo puede asignar
    convocatorias o listar a todo el personal).
    """
    resp = httpx.post(
        _centro_url("/auth/login"),
        json={"numero_identificacion": numero_identificacion, "clave": clave},
        timeout=30,
    )
    if resp.status_code != 200:
        return {"error": resp.json().get("detail", resp.text)}
    return resp.json()


@tool
@trazable(name="crear_solicitud")
def crear_solicitud(
    convocatoria_id: str,
    solicitante_id: str,
    justificacion: str,
    equipo_sugerido: list[str] | None = None,
) -> dict:
    """Registra la solicitud de postulación de un investigador/consultor a una
    convocatoria. Queda en estado 'pendiente': crear una solicitud NO asigna a
    nadie, la asignación la deciden los directivos con asignar_convocatoria.

    convocatoria_id:  id de la convocatoria (del RAG, ej. CONV-007).
    solicitante_id:   id del miembro del personal que se postula (PER-...).
    justificacion:    por qué el solicitante encaja en la convocatoria.
    equipo_sugerido:  personal sugerido (PER-...), opcional.
    """
    resp = httpx.post(
        _centro_url("/solicitudes"),
        json={
            "convocatoria_id": convocatoria_id,
            "solicitante_id": solicitante_id,
            "justificacion": justificacion,
            "equipo_sugerido": equipo_sugerido or [],
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        return {"error": resp.json().get("detail", resp.text)}
    return resp.json()


@tool
@trazable(name="asignar_convocatoria")
def asignar_convocatoria(
    convocatoria_id: str,
    directivo_id: str,
    equipo_asignado: list[str],
    justificacion: str,
    solicitudes_consideradas: list[str] | None = None,
) -> dict:
    """Asigna formalmente un equipo del Centro a una convocatoria. Exclusivo de
    directivos: directivo_id debe corresponder a una persona con rol
    'directivo' (si no, la API responde 403). Marca como 'aprobada' las
    solicitudes consideradas.

    convocatoria_id:            convocatoria a asignar (del RAG, ej. CONV-007).
    directivo_id:                id del directivo que asigna (PER-...).
    equipo_asignado:             personal asignado a la convocatoria (PER-...).
    justificacion:                por qué este equipo, según convocatoria +
                                  solicitudes + experticia.
    solicitudes_consideradas:    ids de solicitudes tenidas en cuenta (SOL-...),
                                  opcional.
    """
    resp = httpx.post(
        _centro_url("/asignaciones"),
        json={
            "convocatoria_id": convocatoria_id,
            "directivo_id": directivo_id,
            "equipo_asignado": equipo_asignado,
            "justificacion": justificacion,
            "solicitudes_consideradas": solicitudes_consideradas or [],
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        return {"error": resp.json().get("detail", resp.text)}
    return resp.json()


def get_local_tools() -> list:
    """Lista de herramientas locales del agente (semana 2: al menos 3)."""
    return [autenticarse_centro, crear_solicitud, asignar_convocatoria]