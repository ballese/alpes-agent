"""CRV write-gate del Judge Agent.

Este subpaquete implementa el patrón **Critique -> Refine -> Validate** para
las tres tools críticas de escritura del agente principal (crear_solicitud,
asignar_convocatoria, escalar).

Módulos:

* ``rules``    - Reglas deterministas de crítica (fase 1 del CRV).
* ``refine``   - Un solo LLM call acotado que reescribe args (fase 2).
* ``pipeline`` - Orquesta crítica -> refine -> re-crítica (fase 3).

El endpoint HTTP que expone este pipeline vive en ``judge/app.py``
(``POST /gate``).
"""
