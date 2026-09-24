"""Segundo agente (Juez) — patrón *critique-refine-validate* sobre A2A.

Este paquete es DELIBERADAMENTE independiente del ejecutor (`agent/`): el
Juez recibe únicamente `{original_user_question, proposed_action,
authenticated_context}` a través del endpoint A2A (ver `judge/server.py`)
y verifica el contexto por su propia cuenta con `judge/verification.py`.

Aislamiento (por qué):
- El Juez NO ve el `reasoning_trace` ni el historial de mensajes del ejecutor.
- El Juez NO llama herramientas de escritura (`crear_solicitud`,
  `asignar_convocatoria`, `escalar`). Se hace cumplir en `judge/verification.py`.
- El `rol_claimed` que llega en `authenticated_context` es DATOS SIN VERIFICAR:
  la verdad la da `verify_persona` (hit propio al backend).

Contrato de entrada/salida:
- Entrada A2A: `message/send` con parts JSON tipadas (Pydantic con `extra="ignore"`).
- Salida A2A: `{verdict: APPROVE|REFINE|REJECT, reason, refined_args?, trace}`.
"""
