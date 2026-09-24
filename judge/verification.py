"""Verificación *independiente* del contexto — el Juez consulta la verdad
por su propia cuenta, sin confiar en lo que dice el ejecutor.

Estas funciones son de SOLO LECTURA y golpean los mismos backends que el
servidor MCP y `agent/tools.py`, pero desde el proceso del Juez. Cada una
tiene un tope duro de 1 llamada por verdict (se hace cumplir en
`judge/agent.py`).

ADVERTENCIA DE SEGURIDAD: este módulo NUNCA debe importar ni invocar las
tools de escritura (`crear_solicitud`, `asignar_convocatoria`, `escalar`).
El test `test_semana_juez.py::test_juez_no_llama_tools_de_escritura` hace
un lint estático sobre este archivo para exigirlo.
"""

from __future__ import annotations

import httpx

from cli.config import get_settings


def _centro_url(path: str) -> str:
    return f"{get_settings().api_base_url}/centro-proyectos{path}"


def _rag_ask(pregunta: str) -> dict:
    """Copia mínima del cliente RAG del servidor MCP.

    El Juez usa su propio login para no compartir estado con el ejecutor
    (aislamiento). El caché es por-proceso; en CI es un miss barato.
    """
    settings = get_settings()
    login = httpx.post(
        f"{settings.rag_base_url}/login",
        json={"email": settings.rag_email, "password": settings.rag_password},
        timeout=30,
    )
    login.raise_for_status()
    token = login.json()["access_token"]
    resp = httpx.post(
        f"{settings.rag_base_url}/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "pregunta": pregunta,
            "collection": settings.rag_collection,
            "evaluate": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def verify_persona(persona_id: str, token: str) -> dict:
    """Rol y experticia REALES de la persona autenticada.

    Devuelve `{ok: bool, rol, areas_expertise, error?}`. Fail-closed:
    cualquier error de red se convierte en `ok=False`. El Juez usa el
    resultado para R3 (autorización) y R5 (¿el rol pedido en el prompt
    coincide con la realidad?).
    """
    try:
        resp = httpx.get(
            _centro_url("/personal/me"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        return {
            "ok": True,
            "persona_id": data.get("id"),
            "rol": data.get("rol"),
            "areas_expertise": data.get("areas_expertise", []),
            "match_persona_id": data.get("id") == persona_id if persona_id else True,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def verify_convocatoria(convocatoria_id: str) -> dict:
    """La convocatoria existe en el RAG y su descripción es recuperable.

    No hace validación semántica — solo comprueba que el ID aparece en la
    respuesta del RAG. R5 (alineación) se apoya en esto sin gastar otra
    llamada.
    """
    try:
        data = _rag_ask(
            f"¿Existe la convocatoria {convocatoria_id}? Descríbela brevemente."
        )
        respuesta = str(data.get("respuesta", ""))
        return {
            "ok": convocatoria_id in respuesta,
            "convocatoria_id": convocatoria_id,
            "descripcion": respuesta[:500],
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}


def lookup_policies(convocatoria_id: str) -> dict:
    """Políticas aplicables a la convocatoria — mismo RAG.

    Solo lo llama el Juez para R5 cuando la tool crítica es
    `crear_solicitud` o `asignar_convocatoria` y necesita contrastar
    restricciones de sector u overhead.
    """
    try:
        data = _rag_ask(
            f"¿Qué políticas de participación aplican a la convocatoria "
            f"{convocatoria_id}? (overhead, contrapartida, sectores)"
        )
        return {"ok": True, "politicas": str(data.get("respuesta", ""))[:800]}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
