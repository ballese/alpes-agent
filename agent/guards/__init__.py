"""Guardrails aplicados a las tools del agente principal.

Este subpaquete contiene el lado-agente del write-gate CRV: el cliente HTTP
al judge (``gate_client``) y el decorador ``@critical_write`` que envuelve las
tres tools críticas antes de que el LLM las ejecute.

El diseño es **fail-open**: si el judge no responde en el timeout esperado o
si algo falla en la comunicación, la tool se ejecuta con los args originales
y solo se emite un warning a stderr. Nunca se rompe el flujo del usuario por
una caída del auditor.
"""
