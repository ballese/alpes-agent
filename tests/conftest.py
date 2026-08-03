"""Configuración de pytest.

Pone la raíz del proyecto en `sys.path` para que `contract.py` y el código del
equipo se puedan importar sin instalar el paquete.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
