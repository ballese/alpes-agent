"""Cliente HTTP al endpoint ``POST /gate`` del Judge Agent.

Encapsula el fetch síncrono a ``JUDGE_BASE_URL/gate`` con timeout y
manejo de errores. **Fail-open**: cualquier fallo devuelve ``None`` y el
decorador ``@critical_write`` interpreta eso como "el auditor no está
disponible, ejecuta la tool con args originales".
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from observability.tracing import trazable

_LOG = logging.getLogger("agent.guards.gate_client")

# Timeout total (conexión + lectura) para el /gate call. Debe ser mayor que el
# refine LLM interno del judge (5s) más un margen para la crítica y el HTTP.
_GATE_TIMEOUT_S = 8.0


def _judge_base_url() -> str:
    # Se lee cada llamada: útil para tests que hacen monkeypatch de env vars.
    return os.getenv("JUDGE_BASE_URL", "http://judge:8000").rstrip("/")


@trazable(name="crv_gate", run_type="chain", tags=["crv", "gate"])
def call_gate(tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Invoca el pipeline CRV del judge para ``(tool, args)``.

    Returns:
        dict con las claves ``status``, ``args_final``, ``issues_initial``,
        ``issues_final``, ``refine_used`` y ``refine_reason`` cuando el judge
        responde correctamente; ``None`` si el judge está caído, hay timeout,
        el status es 5xx, o el JSON no cumple el contrato esperado.
    """
    url = f"{_judge_base_url()}/gate"
    payload = {"tool": tool, "args": args}

    try:
        with httpx.Client(timeout=_GATE_TIMEOUT_S) as client:
            resp = client.post(url, json=payload)
    except httpx.TimeoutException:
        _LOG.warning("write-gate: timeout (%.1fs) llamando a %s", _GATE_TIMEOUT_S, url)
        return None
    except httpx.HTTPError as exc:
        _LOG.warning(
            "write-gate: error HTTP (%s) llamando a %s", exc.__class__.__name__, url
        )
        return None

    if resp.status_code >= 500:
        _LOG.warning("write-gate: judge devolvió %s", resp.status_code)
        return None

    if resp.status_code >= 400:
        # 400 = tool desconocida en el registry del judge. Es un error de
        # configuración del agente (aplicamos @critical_write a una tool que el
        # judge no reconoce). Fail-open y avisar por logs.
        _LOG.warning(
            "write-gate: tool '%s' no reconocida por el judge (status=%s, body=%s)",
            tool,
            resp.status_code,
            resp.text[:200],
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        _LOG.warning("write-gate: respuesta del judge no es JSON válido")
        return None

    if not isinstance(data, dict) or "status" not in data or "args_final" not in data:
        _LOG.warning("write-gate: respuesta del judge no cumple el contrato esperado")
        return None

    return data
