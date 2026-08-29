"""Memoria de largo plazo en PostgreSQL para un usuario demo."""

from typing import Any, Dict, Optional

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore
from psycopg import connect
from psycopg.rows import dict_row

from cli.config import get_settings

_GLOBAL_STORE: Optional[BaseStore] = None
SINGLE_USER_ID = "usuario_centro_demo"


def _namespace() -> tuple[str, str]:
    return ("profiles", SINGLE_USER_ID)


def build_store(backend: str = "postgres") -> BaseStore:
    """Retorna el store de memoria larga listo para usar."""
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        if backend == "memory":
            _GLOBAL_STORE = InMemoryStore()
        elif backend == "postgres":
            conn = connect(
                get_settings().database_url,
                autocommit=True,
                row_factory=dict_row,
            )
            _GLOBAL_STORE = PostgresStore(conn)
            _GLOBAL_STORE.setup()
        else:
            raise ValueError(f"Backend no soportado: {backend}")
    return _GLOBAL_STORE


def get_user_profile(store: BaseStore, user_id: str = SINGLE_USER_ID) -> Dict[str, Any]:
    """Recupera el perfil único. user_id se acepta solo por compatibilidad."""
    item = store.get(_namespace(), "profile")
    return item.value if item else {}


def save_user_profile(store: BaseStore, user_id: str, profile_data: Dict[str, Any]) -> None:
    """Actualiza el perfil único. user_id se ignora a propósito."""
    namespace = _namespace()
    existente = store.get(namespace, "profile")
    data = existente.value if existente else {}
    data.update(profile_data)
    store.put(namespace, "profile", data)
