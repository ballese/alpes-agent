"""Servidor A2A del Juez — FastAPI + JSON-RPC 2.0 mínimo.

Endpoints:
- `GET /.well-known/agent.json` — *agent card* (auto-descripción A2A).
- `POST /` — JSON-RPC 2.0. Único método soportado: `message/send`.

Aislamiento en el borde:
Pydantic descarta silenciosamente cualquier campo no whitelisted del payload
(`model_config = ConfigDict(extra="ignore")`). Es la última defensa contra
que el ejecutor filtre su `reasoning_trace` o el historial de mensajes.

En CI se importa la ASGI app con `get_judge_app()` (ver `contract.py`) y se
prueba con `httpx.ASGITransport`, sin arrancar uvicorn.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from judge.agent import judge_tool_call


class ProposedAction(BaseModel):
    """Acción propuesta por el ejecutor. Solo dos campos: nombre + args."""

    model_config = ConfigDict(extra="ignore")

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class AuthenticatedContext(BaseModel):
    """Contexto de sesión del usuario. `rol_claimed` NO es de confianza."""

    model_config = ConfigDict(extra="ignore")

    token: str | None = None
    persona_id: str | None = None
    rol_claimed: str | None = None


class JudgePayload(BaseModel):
    """Payload aislado que llega en `params.message.parts[0]`."""

    model_config = ConfigDict(extra="ignore")

    original_user_question: str
    proposed_action: ProposedAction
    authenticated_context: AuthenticatedContext = Field(
        default_factory=AuthenticatedContext
    )


def _agent_card(base_url: str = "http://localhost:8090") -> dict:
    """Agent Card mínima conforme a la especificación A2A del laboratorio 15."""
    return {
        "name": "juez-centro-proyectos",
        "description": (
            "Juez que evalúa acciones propuestas por el agente ejecutor del "
            "Centro de Proyectos usando el patrón critique-refine-validate. "
            "Recibe únicamente {original_user_question, proposed_action, "
            "authenticated_context} y devuelve APPROVE | REFINE | REJECT."
        ),
        "url": base_url,
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "judge_tool_call",
                "name": "Juzgar llamada a herramienta",
                "description": (
                    "Aplica la rúbrica de 5 reglas y (para tools críticas) "
                    "una verificación de contexto independiente."
                ),
                "tags": ["judge", "a2a", "critique-refine-validate"],
            }
        ],
    }


def _extract_payload(params: dict) -> dict | None:
    """A2A `message/send`: params.message.parts[0] transporta el JSON.

    Aceptamos dos formas por robustez:
    - `parts=[{"type": "data", "data": {...}}]` (forma canónica).
    - `parts=[{"type": "text", "text": "<json>"}]` (fallback).
    Cualquier otra forma devuelve None → el llamador emite JSON-RPC error.
    """
    message = (params or {}).get("message") or {}
    parts = message.get("parts") or []
    if not parts:
        return None
    part = parts[0]
    if isinstance(part, dict) and isinstance(part.get("data"), dict):
        return part["data"]
    if isinstance(part, dict) and isinstance(part.get("text"), str):
        import json

        try:
            data = json.loads(part["text"])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def build_app() -> FastAPI:
    """Construye la ASGI app del Juez.

    Se separa de la variable módulo para que las pruebas puedan construir
    apps aisladas si lo necesitan.
    """
    app = FastAPI(title="Juez Centro de Proyectos", version="1.0.0")

    @app.get("/.well-known/agent.json")
    def agent_card() -> dict:
        return _agent_card()

    @app.post("/")
    async def jsonrpc(body: dict) -> dict:
        rpc_id = body.get("id")
        if body.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        if body.get("method") != "message/send":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": "Method not found"},
            }

        raw = _extract_payload(body.get("params") or {})
        if raw is None:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32602,
                    "message": "Invalid params: falta parts[0].data",
                },
            }

        try:
            payload = JudgePayload.model_validate(raw)
        except Exception as exc:  # pydantic ValidationError o similares
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32602, "message": f"Invalid params: {exc}"},
            }

        verdict = judge_tool_call(payload.model_dump())
        return {"jsonrpc": "2.0", "id": rpc_id, "result": verdict}

    return app


# La app a nivel módulo es lo que uvicorn levanta.
app = build_app()
