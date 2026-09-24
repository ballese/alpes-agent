"""Judge agent skeleton.

Servicio FastAPI que audita las acciones del agente principal.

Este esqueleto expone dos superficies:

1. Endpoints legados (``/health``, ``/audit``) para pruebas manuales rapidas.
2. Superficie **A2A** minima (``/.well-known/agent-card.json`` + JSON-RPC 2.0
   en ``POST /``) que implementa unicamente el metodo ``message/send``.

La logica de auditoria real se anadira mas adelante: por ahora la
respuesta a ``message/send`` es siempre ``ok`` con un eco del texto recibido
para facilitar depuracion.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Judge Agent", version="0.1.0")


# ---------------------------------------------------------------------------
# Endpoints legados (backwards compatible con el esqueleto anterior)
# ---------------------------------------------------------------------------


class AuditRequest(BaseModel):
    """Payload legado del endpoint ``/audit``."""

    message: str = Field(..., description="Message or action to audit")


class AuditResponse(BaseModel):
    status: str
    received: str


@app.get("/health")
def health() -> dict:
    """Liveness endpoint usado por el healthcheck de Docker."""
    return {"status": "healthy"}


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest) -> AuditResponse:
    """Endpoint legado. Se conserva para no romper smoke tests previos."""
    return AuditResponse(status="ok", received=req.message)


# ---------------------------------------------------------------------------
# Superficie A2A: Agent Card + JSON-RPC 2.0
# ---------------------------------------------------------------------------


AGENT_CARD: dict[str, Any] = {
    "name": "JudgeAgent",
    "description": "Auditor de acciones del agente del Centro de Proyectos y Consultoria.",
    "version": "0.1.0",
    # ``url`` es la URL del endpoint JSON-RPC segun la spec A2A.
    "url": "http://judge:8000/",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "audit",
            "name": "audit",
            "description": "Recibe un mensaje del agente principal y responde ok.",
            "tags": ["audit", "skeleton"],
        }
    ],
}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict[str, Any]:
    """Publica el Agent Card en la ubicacion estandar de A2A."""
    return AGENT_CARD


# --- Modelos JSON-RPC 2.0 (subset) -----------------------------------------


class JsonRpcRequest(BaseModel):
    jsonrpc: str
    id: Optional[Any] = None
    method: str
    params: Optional[dict[str, Any]] = None


def _rpc_error(rpc_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        },
    )


def _rpc_result(rpc_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _extract_text(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    textos = [
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("kind") == "text"
    ]
    return "".join(textos)


def _build_agent_message(text: str) -> dict[str, Any]:
    return {
        "kind": "message",
        "role": "agent",
        "messageId": uuid4().hex,
        "parts": [{"kind": "text", "text": text}],
    }


@app.post("/")
async def jsonrpc_endpoint(request: Request) -> Any:
    """Dispatcher JSON-RPC 2.0. Solo implementa ``message/send`` por ahora."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _rpc_error(None, -32700, "Parse error")

    try:
        rpc = JsonRpcRequest(**body)
    except Exception as exc:  # noqa: BLE001
        return _rpc_error(
            body.get("id") if isinstance(body, dict) else None,
            -32600,
            f"Invalid Request: {exc}",
        )

    if rpc.method != "message/send":
        return _rpc_error(rpc.id, -32601, f"Method not found: {rpc.method}")

    params = rpc.params or {}
    message = params.get("message")
    if not isinstance(message, dict):
        return _rpc_error(rpc.id, -32602, "Invalid params: 'message' missing")

    try:
        text_in = _extract_text(message)
        # TODO: aqui ira la logica real de auditoria (LLM-as-judge, reglas,
        # LangSmith trace inspection, etc.). Por ahora el judge solo confirma
        # que recibio el mensaje.
        preview = (text_in[:80] + "...") if len(text_in) > 80 else text_in
        reply_text = f"ok (received: {preview})" if preview else "ok"
        return _rpc_result(rpc.id, _build_agent_message(reply_text))
    except Exception as exc:  # noqa: BLE001
        return _rpc_error(rpc.id, -32603, f"Internal error: {exc}")
