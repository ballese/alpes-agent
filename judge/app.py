"""Judge agent skeleton.

Servicio FastAPI que audita las acciones del agente principal.

Superficies expuestas:

1. Endpoints legados (``/health``, ``/audit``, ``/rubric``) para pruebas
   manuales rapidas.
2. Superficie **A2A** minima (``/.well-known/agent-card.json`` + JSON-RPC 2.0
   en ``POST /``) que implementa el metodo ``message/send`` con **doble
   proposito**:

   - Si el TextPart entrante contiene un JSON con ``kind`` in
     ``{"critique", "validate"}``, se enruta a ``judge.audit`` y se devuelve
     la respuesta plana ``OK`` o ``REFINE: <razon>``.
   - En cualquier otro caso, se enruta a ``judge.rubric.evaluate`` (auditoria
     post-respuesta contra prompt injection) y se devuelve el verdict
     serializado como JSON dentro de un TextPart.

De esta forma el mismo endpoint sirve el write-gate (Agent 1 -> Agent 2) y la
rubrica de salida sin abrir dos surfaces distintas.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from judge import audit, rubric

# Sin esto los loggers ``judge.*`` no tienen handler y sus INFO se pierden;
# asi ``docker compose logs -f judge`` muestra lo que el juez procesa.
logging.basicConfig(
    level=os.getenv("JUDGE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
_LOG = logging.getLogger("judge.app")

_LOG_TEXT_MAX_LEN = 300

app = FastAPI(title="Judge Agent", version="0.3.0-a2a")


def _trunc(text: str, max_len: int = _LOG_TEXT_MAX_LEN) -> str:
    """Recorta ``text`` para que los logs no vuelquen mensajes enormes."""
    return text if len(text) <= max_len else text[:max_len] + "..."


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
def audit_legacy(req: AuditRequest) -> AuditResponse:
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
# Superficie A2A: Agent Card + JSON-RPC 2.0
# ---------------------------------------------------------------------------


AGENT_CARD: dict[str, Any] = {
    "name": "JudgeAgent",
    "description": (
        "Auditor A2A del Centro de Proyectos: revisa acciones criticas del "
        "agente principal (critique/validate por rubrica por tool) y aplica "
        "la rubrica de prompt-injection sobre respuestas finales."
    ),
    "version": "0.3.0-a2a",
    # ``url`` es la URL del endpoint JSON-RPC segun la spec A2A.
    "url": "http://judge:8000/",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "critique",
            "name": "critique",
            "description": (
                "Revisa los args que el agente 1 quiere pasarle a una tool "
                "critica contra la rubrica de esa tool. Responde 'OK' o "
                "'REFINE: <razon>'."
            ),
            "tags": ["audit", "critique", "write-gate"],
        },
        {
            "id": "validate",
            "name": "validate",
            "description": (
                "Revisa los args refinados por el agente 1 tras un REFINE "
                "previo. Responde 'OK' o 'REFINE: <razon>'."
            ),
            "tags": ["audit", "validate", "write-gate"],
        },
        {
            "id": "rubric",
            "name": "rubric",
            "description": (
                "Aplica la rubrica de prompt-injection y fuga de secretos al "
                "texto final del agente. Devuelve un verdict JSON "
                "(pass/warn/block)."
            ),
            "tags": ["audit", "rubric", "prompt-injection"],
        },
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


def _try_parse_audit_payload(text: str) -> dict[str, Any] | None:
    """Intenta interpretar el TextPart como payload de write-gate.

    Devuelve el dict si tiene forma ``{"kind": "critique"|"validate", ...}``.
    En cualquier otro caso devuelve ``None`` y el dispatcher enrutara a la
    rubrica de prompt-injection.
    """
    if not text or not text.lstrip().startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("kind") not in ("critique", "validate"):
        return None
    return obj


@app.post("/")
async def jsonrpc_endpoint(request: Request) -> Any:
    """Dispatcher JSON-RPC 2.0. Enruta ``message/send`` a audit o rubrica."""
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
        audit_payload = _try_parse_audit_payload(text_in)

        if audit_payload is not None:
            # Write-gate: critique o validate segun `kind`.
            kind = audit_payload["kind"]
            reply_text = (
                audit.critique(audit_payload)
                if kind == "critique"
                else audit.validate(audit_payload)
            )
            _LOG.info(
                "A2A %s tool=%s args=%s -> %s",
                kind,
                audit_payload.get("tool"),
                _trunc(json.dumps(audit_payload.get("args"), ensure_ascii=False)),
                reply_text,
            )
        else:
            # Rubrica de prompt-injection sobre la respuesta final del agente.
            verdict = rubric.evaluate(text_in)
            reply_text = json.dumps(verdict, ensure_ascii=False)
            # Sin evidencia: podria contener un secreto detectado por R3.
            _LOG.info(
                "A2A rubric text=%r -> %s score=%s",
                _trunc(text_in),
                verdict["verdict"],
                verdict["score"],
            )

        return _rpc_result(rpc.id, _build_agent_message(reply_text))
    except Exception as exc:  # noqa: BLE001
        return _rpc_error(rpc.id, -32603, f"Internal error: {exc}")
