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

import json
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from judge import rubric
from judge.gate import pipeline as gate_pipeline
from judge.gate.pipeline import UnknownToolError

app = FastAPI(title="Judge Agent", version="0.2.0-demo")


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
# Endpoint directo de rubrica (para curl y pruebas manuales)
# ---------------------------------------------------------------------------


class RubricRequest(BaseModel):
    text: str = Field(..., description="Texto a evaluar contra la rubrica.")


@app.post("/rubric")
def rubric_endpoint(req: RubricRequest) -> dict[str, Any]:
    """Aplica la rubrica al texto recibido y devuelve el verdict como JSON."""
    return rubric.evaluate(req.text)


# ---------------------------------------------------------------------------
# Endpoint CRV Gate (usado por el decorador @critical_write del agente)
# ---------------------------------------------------------------------------


class GateRequest(BaseModel):
    """Payload del write-gate CRV.

    ``tool`` debe ser una de las tools críticas de escritura registradas en
    ``judge.gate.rules.CHECKERS``. ``args`` es el dict que el agente iba a
    pasarle a la tool.
    """

    tool: str = Field(..., description="Nombre de la tool crítica.")
    args: dict[str, Any] = Field(
        default_factory=dict, description="Args originales que el agente construyó."
    )


@app.post("/gate")
def gate_endpoint(req: GateRequest) -> JSONResponse:
    """Ejecuta el pipeline CRV y devuelve la traza completa como JSON.

    Códigos HTTP:
        200 - status ``pass`` o ``refine-passed`` (payload utilizable).
        200 - status ``block`` (payload con motivo, pero el agente decide qué hacer).
        400 - tool desconocida (no está en el registry).
    """
    try:
        result = gate_pipeline.run_gate(req.tool, req.args)
    except UnknownToolError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(status_code=200, content=result.as_dict())


# ---------------------------------------------------------------------------
# Superficie A2A: Agent Card + JSON-RPC 2.0
# ---------------------------------------------------------------------------


AGENT_CARD: dict[str, Any] = {
    "name": "JudgeAgent",
    "description": "Auditor de acciones del agente del Centro de Proyectos y Consultoria.",
    "version": "0.2.0-demo",
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
            "description": (
                "Recibe la respuesta final del agente principal y devuelve un "
                "verdict JSON (pass/warn/block) segun la rubrica v0.2.0-demo."
            ),
            "tags": ["audit", "rubric", "prompt-injection"],
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
        # Aplica la rubrica al texto final del agente principal y devuelve el
        # verdict serializado como JSON dentro de un TextPart. De esta forma el
        # cliente A2A no necesita cambios: sigue recibiendo un string.
        verdict = rubric.evaluate(text_in)
        reply_text = json.dumps(verdict, ensure_ascii=False)
        return _rpc_result(rpc.id, _build_agent_message(reply_text))
    except Exception as exc:  # noqa: BLE001
        return _rpc_error(rpc.id, -32603, f"Internal error: {exc}")
