"""Memoria de corto plazo con checkpointer PostgreSQL."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import connect
from psycopg.rows import dict_row

from cli.config import get_settings


def build_checkpointer(backend: str = "postgres") -> BaseCheckpointSaver:
    """Retorna un checkpointer síncrono listo para usar."""
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if backend == "postgres":
        conn = connect(
            get_settings().database_url,
            autocommit=True,
            row_factory=dict_row,
        )
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    raise ValueError(f"Backend no soportado: {backend}")
