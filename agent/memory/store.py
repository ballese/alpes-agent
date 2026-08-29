"""Memoria de largo plazo y perfiles (laboratorio 12) — Centro de Proyectos."""

from typing import Any, Dict, Optional
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

_GLOBAL_STORE: Optional[BaseStore] = None


def build_store() -> BaseStore:
    """Retorna la instancia global del Store de memoria de largo plazo."""
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        _GLOBAL_STORE = InMemoryStore()
    return _GLOBAL_STORE


def get_user_profile(store: BaseStore, user_id: str) -> Dict[str, Any]:
    """Recupera los datos del perfil de un usuario en el namespace ('profiles', user_id)."""
    item = store.get(("profiles", user_id), "profile")
    return item.value if item else {}


def save_user_profile(store: BaseStore, user_id: str, profile_data: Dict[str, Any]) -> None:
    """Persiste o actualiza los datos del perfil de un usuario en el Store."""
    namespace = ("profiles", user_id)
    existente = store.get(namespace, "profile")
    data = existente.value if existente else {}
    data.update(profile_data)
    store.put(namespace, "profile", data)