"""Cliente A2A para llamar al Juez desde el ejecutor.

Es un thin wrapper sobre httpx con JSON-RPC 2.0. Fail-closed en el borde:
si el Juez no responde o devuelve un error, sintetizamos un REJECT local
para que el ejecutor NUNCA proceda con la tool crítica en ausencia del
Juez.

En pruebas se puede pasar un `transport=httpx.ASGITransport(app=...)` para
correr todo en proceso sin sockets.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from cli.config import get_settings


def _jsonrpc_request(payload: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "data", "data": payload}],
            }
        },
    }


def solicit_verdict(
    tool_name: str,
    args: dict[str, Any],
    context: dict[str, Any],
    original_user_question: str,
    *,
    client: httpx.Client | None = None,
) -> dict:
    """Bloquea hasta que el Juez conteste (o hasta el timeout configurado).

    context = {"token": str | None, "persona_id": str | None,
               "rol_claimed": str | None}
    """
    settings = get_settings()
    payload = {
        "original_user_question": original_user_question,
        "proposed_action": {"tool_name": tool_name, "args": args},
        "authenticated_context": context,
    }
    body = _jsonrpc_request(payload)

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            base_url=settings.judge_base_url, timeout=settings.judge_timeout
        )

    try:
        resp = client.post("/", json=body)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Fail-closed: sin Juez alcanzable, NO se ejecuta la tool crítica.
        return {
            "verdict": "REJECT",
            "reason": f"Juez no alcanzable ({exc.__class__.__name__}: {exc})",
            "trace": ["a2a_client: fail-closed por error de red"],
        }
    finally:
        if owns_client:
            client.close()

    if "error" in data:
        return {
            "verdict": "REJECT",
            "reason": f"Juez devolvió error JSON-RPC: {data['error']}",
            "trace": ["a2a_client: fail-closed por JSON-RPC error"],
        }
    result = data.get("result") or {}
    if result.get("verdict") not in {"APPROVE", "REFINE", "REJECT"}:
        return {
            "verdict": "REJECT",
            "reason": "Juez devolvió veredicto inválido",
            "trace": ["a2a_client: fail-closed por veredicto inválido"],
        }
    return result
