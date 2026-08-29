"""Memoria de corto plazo con checkpointers (laboratorio 11) — Centro de Proyectos."""

import sqlite3
from pathlib import Path
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

# Ruta persistente en disco en la raíz del proyecto
DB_PATH = Path(__file__).resolve().parent.parent.parent / "checkpoints.sqlite"


def build_checkpointer(backend: str = "sqlite") -> BaseCheckpointSaver:
    """Retorna un BaseCheckpointSaver síncrono según el backend: sqlite | memory."""
    if backend == "sqlite":
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        return SqliteSaver(conn)
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    raise ValueError(f"Backend no soportado: {backend}")