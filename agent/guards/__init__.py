"""Guardrails aplicados a las tools del agente principal.

Este subpaquete implementa el lado-agente del write-gate como una
conversacion A2A con el Judge Agent:

* ``critical_write`` es el decorador que envuelve las tools criticas y
  orquesta el ciclo critique -> refine local -> validate.
* ``audit_context`` guarda el `user_request` y el `user_profile` del turno
  actual en un `ContextVar`, para que el decorador los incluya en el payload
  A2A sin cambiar la firma de las tools.

El diseno es **fail-open**: si el juez no responde en el timeout esperado o
algo falla en la comunicacion, la tool se ejecuta con los args originales y
solo se emite un warning. El auditor nunca es punto unico de falla.
"""
