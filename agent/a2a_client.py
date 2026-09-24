"""Cliente A2A minimo del agente principal hacia el Judge Agent.

Implementa a mano el subconjunto necesario del protocolo A2A
(https://a2a-protocol.org) para el esqueleto:

- Descubrimiento via ``GET /.well-known/agent-card.json``.
- Envio de mensajes via JSON-RPC 2.0 con el metodo ``message/send``.

No se usa el SDK oficial para mantener las dependencias al minimo:
solo ``httpx``, que ya esta en ``requirements.txt``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx


class A2AClient:
    """Cliente JSON-RPC 2.0 muy pequeno para hablar con un agente A2A."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        # Normalizamos: el endpoint JSON-RPC del judge esta en la raiz "/".
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def fetch_agent_card(self) -> dict[str, Any]:
        """Obtiene el Agent Card publicado por el judge."""
        url = f"{self.base_url}/.well-known/agent-card.json"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def send_message(self, text: str) -> str:
        """Envia un mensaje de texto via ``message/send`` y devuelve el texto de respuesta.

        Devuelve la concatenacion de los ``TextPart`` del ``Message`` de respuesta.
        Si el resultado no contiene texto, devuelve una cadena vacia.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": uuid4().hex,
                    "parts": [{"kind": "text", "text": text}],
                }
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/", json=payload)
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            err = data["error"]
            raise RuntimeError(
                f"Judge devolvio error JSON-RPC {err.get('code')}: {err.get('message')}"
            )

        result = data.get("result") or {}
        parts = result.get("parts") or []
        textos = [
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and p.get("kind") == "text"
        ]
        return "".join(textos)


def get_judge_client() -> A2AClient:
    """Construye un ``A2AClient`` apuntando al judge configurado en settings."""
    # Import diferido para evitar ciclos y para no forzar la config al importar
    # el modulo desde tests o utilidades.
    from cli.config import get_settings

    return A2AClient(base_url=get_settings().judge_base_url)
