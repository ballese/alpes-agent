"""[SEMANA 4 — PENDIENTE] Memoria de corto plazo con checkpointers (laboratorio 11).

El equipo debe implementar `build_checkpointer(backend)` retornando un
checkpointer de LangGraph que persista en disco (SqliteSaver o superior),
y conectar el CLI para que cada conversación use un `thread_id` propio.
"""


def build_checkpointer(backend: str = "sqlite"):
    """Retorna un BaseCheckpointSaver según el backend: memory | sqlite | postgres."""
    raise NotImplementedError(
        "Semana 4: implementar la memoria de corto plazo siguiendo el laboratorio 11."
    )
