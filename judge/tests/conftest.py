"""Pytest bootstrap para las pruebas del Judge Agent.

Asegura que la raiz del repo este en ``sys.path`` para poder hacer
``from judge import rubric`` sin necesidad de instalar el paquete ni
modificar ``pyproject.toml``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
