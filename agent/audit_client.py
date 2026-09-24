"""Cliente sincrono del write-gate hacia el Judge Agent via A2A.

`@critical_write` es un decorador sincrono (las tools de LangChain lo llaman
desde `tool.invoke(...)`). El cliente A2A oficial (`agent/a2a_client.py`) es
asincrono. Este modulo hace de puente:

* Ejecuta `A2AClient.send_message(...)` en un hilo aislado con su propio event
  loop (mismo truco que `agent/reasoning/react.py::_ejecutar_tool`) para no
  chocar con el event loop del CLI si existe.
* Serializa el payload como JSON dentro del TextPart. El judge lo reconoce por
  la presencia del campo `kind` (`critique` | `validate`).
* Envuelve la llamada en `@trazable` para que cada peticion al juez aparezca
  como un span independiente en LangSmith.

Fail-open a `"OK"`: cualquier excepcion (judge caido, timeout, error HTTP)
degrada a "aprobado", igual que la logica interna del juez. El decorador
decide en modo `advisory`/`blocking` que hacer con esa respuesta.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from typing import Any, Literal

from agent.a2a_client import get_judge_client
from observability.tracing import trazable

_LOG = logging.getLogger("agent.audit_client")

Phase = Literal["critique", "validate"]


def _run_async(coro):
    """Ejecuta una coroutine en un hilo aislado con su propio event loop.

    Necesario porque `send_message` es async y el decorador es sync; usar
    `asyncio.run` directamente rompe si ya hay un loop corriendo.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _send(payload: dict[str, Any]) -> str:
    """Envia el payload al juez y devuelve el texto de respuesta.

    Cualquier excepcion se convierte en `"OK"` (fail-open).
    """
    try:
        client = get_judge_client()
        text = json.dumps(payload, ensure_ascii=False)
        return _run_async(client.send_message(text))
    except Exception as exc:  # noqa: BLE001
        _LOG.info("audit_client fail-open (%s): %s", exc.__class__.__name__, exc)
        return "OK"


@trazable(name="a2a_ask_judge", run_type="chain", tags=["a2a", "critique"])
def ask_critique(payload: dict[str, Any]) -> str:
    """Envia una peticion `critique` al juez. Payload debe traer `tool`, `args`,
    `user_request`, `user_profile`. Devuelve `"OK"` o `"REFINE: ..."`.
    """
    payload = {**payload, "kind": "critique"}
    return _send(payload)


@trazable(name="a2a_ask_judge", run_type="chain", tags=["a2a", "validate"])
def ask_validate(payload: dict[str, Any]) -> str:
    """Envia una peticion `validate` al juez tras un refine local. Devuelve
    `"OK"` o `"REFINE: ..."`.
    """
    payload = {**payload, "kind": "validate"}
    return _send(payload)
