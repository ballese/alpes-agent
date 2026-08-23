"""Servidor MCP del equipo — herramientas de SOLO LECTURA (laboratorio 7).

Caso Centro de Proyectos: agrupa aquí las tools de consulta que alimentan el
razonamiento del agente antes de crear una solicitud, asignar un equipo o
escalar. Dos fuentes de datos reales (nada de mocks):

- RAG institucional (`RAG_BASE_URL`) — convocatorias y políticas públicas.
  No requiere autenticación de persona: es información pública (sección 7 del
  caso). Autenticación de SERVICIO (credenciales del curso en `.env`),
  cacheada en memoria del proceso.
- API empresarial (`API_BASE_URL`, dominio `/centro-proyectos`) — personal,
  historial y solicitudes: datos internos y privados del Centro. Requieren el
  `token` de un miembro autenticado (ver `autenticarse_centro` en
  `agent/tools.py`); este servidor no hace login por cuenta propia porque el
  token pertenece a la sesión de la persona que está chateando.

Dos niveles de acceso a los datos internos, según el rol (sección 3 del
caso): `consultar_mi_perfil` y `consultar_historial_participaciones` sirven
para CUALQUIER persona autenticada; `listar_personal` y `listar_solicitudes`
son EXCLUSIVAS de directivos (el personal no puede ver datos de otros).

Corre como proceso independiente (transporte stdio):

    python mcp_server/server.py
"""

import httpx
from mcp.server.fastmcp import FastMCP

from cli.config import get_settings
from observability.tracing import trazable

mcp = FastMCP("centro-proyectos-lectura")

_rag_token: str | None = None


@trazable(name="rag_login", run_type="tool", tags=["rag"])
def _rag_login() -> str:
    global _rag_token
    if _rag_token is None:
        settings = get_settings()
        resp = httpx.post(
            f"{settings.rag_base_url}/login",
            json={"email": settings.rag_email, "password": settings.rag_password},
            timeout=30,
        )
        resp.raise_for_status()
        _rag_token = resp.json()["access_token"]
    return _rag_token


@trazable(name="rag_ask", run_type="retriever", tags=["rag"])
def _rag_ask(pregunta: str) -> dict:
    settings = get_settings()
    resp = httpx.post(
        f"{settings.rag_base_url}/ask",
        headers={"Authorization": f"Bearer {_rag_login()}"},
        json={
            "pregunta": pregunta,
            "collection": settings.rag_collection,
            "evaluate": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


@trazable(name="centro_get", run_type="tool", tags=["api-empresarial"])
def _centro_get(path: str, token: str, params: dict | None = None) -> dict | list:
    settings = get_settings()
    resp = httpx.get(
        f"{settings.api_base_url}/centro-proyectos{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    if resp.status_code >= 400:
        return {"error": resp.json().get("detail", resp.text)}
    return resp.json()


def _tiene_riesgo(persona: dict) -> bool:
    """Señal de historial individual: hay riesgo si algún proyecto anterior
    salió mal. La API no expone un campo `riesgo`; se deriva de
    `proyectos_anteriores[].resultado` en {"con_riesgo", "fallido"} — el
    caso lista ese historial como parte de la información que alimenta la
    decisión de equipo (sección 7), no como una regla que bloquee acciones.
    """
    return any(
        p.get("resultado") in ("con_riesgo", "fallido")
        for p in persona.get("proyectos_anteriores", [])
    )


def _perfil_resumido(persona: dict) -> dict:
    return {
        "id": persona["id"],
        "nombre_completo": persona["nombre_completo"],
        "rol": persona.get("rol"),
        "seccion": persona.get("seccion"),
        "areas_expertise": persona["areas_expertise"],
        "nivel": persona["nivel"],
        "dedicacion": persona["dedicacion"],
        "riesgo": _tiene_riesgo(persona),
    }


@mcp.tool()
@trazable(name="buscar_convocatoria", run_type="tool", tags=["mcp", "rag"])
def buscar_convocatoria(query: str, entidad: str | None = None) -> dict:
    """Busca convocatorias abiertas en la base de conocimiento pública (RAG),
    filtrando por tema o entidad. Información pública: no requiere
    autenticación.

    query: término o tema de búsqueda (ej. "energías renovables").
    entidad: filtra por entidad convocante (ej. "Minciencias"), opcional.
    """
    pregunta = f"Convocatorias abiertas sobre {query}"
    if entidad:
        pregunta += f" de la entidad {entidad}"
    resultado = _rag_ask(pregunta)
    return {
        "respuesta": resultado["respuesta"],
        "fuentes": resultado.get("files_consulted", []),
    }


@mcp.tool()
@trazable(name="leer_politicas_universidad", run_type="tool", tags=["mcp", "rag"])
def leer_politicas_universidad(convocatoria_id: str) -> dict:
    """Recupera, desde la base de conocimiento pública (RAG), las políticas
    internas de participación (overhead mínimo, contrapartida, consorcios
    exigidos, sectores restringidos, niveles de autorización) aplicables a
    una convocatoria puntual. Información pública: no requiere autenticación.

    convocatoria_id: identificador de la convocatoria a evaluar (ej. CONV-007).
    """
    pregunta = (
        f"¿Qué políticas de participación (overhead mínimo, contrapartida, "
        f"consorcios exigidos, sectores restringidos, niveles de "
        f"autorización) aplican a la convocatoria {convocatoria_id}?"
    )
    resultado = _rag_ask(pregunta)
    return {
        "respuesta": resultado["respuesta"],
        "fuentes": resultado.get("files_consulted", []),
    }


@mcp.tool()
@trazable(name="consultar_mi_perfil", run_type="tool", tags=["mcp", "api-empresarial"])
def consultar_mi_perfil(token: str) -> dict:
    """Devuelve el perfil de la PERSONA AUTENTICADA (cualquier rol):
    experticia, nivel, dedicación e historial. Es lo que usa un miembro del
    personal para evaluar si él mismo encaja en una convocatoria antes de
    postularse — no puede ver el perfil de nadie más (esa es exclusiva del
    directivo, ver listar_personal).

    token: bearer token de la persona autenticada (autenticarse_centro).
    """
    resultado = _centro_get("/personal/me", token)
    if isinstance(resultado, dict) and "error" in resultado:
        return resultado
    return _perfil_resumido(resultado)

if __name__ == "__main__":
    mcp.run(transport="stdio")
