"""Configuración común de pytest.

Añade ``src`` al ``sys.path`` para ejecutar las pruebas sin instalar el paquete.

Convención de la Fase 0: las pruebas que codifican criterios de aceptación de funciones aún no
implementadas se marcan con ``pending(...)``, un ``xfail`` estricto que espera
``NotImplementedError``. Cuando la función se implementa, la prueba pasa (XPASS) y pytest
falla por ser estricta: es la señal para retirar la marca y dejar la prueba como regresión.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pending(phase: str, requirement: str) -> pytest.MarkDecorator:
    """Marca una prueba cuyo código bajo prueba se implementa en una fase posterior."""
    return pytest.mark.xfail(
        raises=NotImplementedError, strict=True, reason=f"{phase} — {requirement}"
    )


@pytest.fixture
def project_root() -> Path:
    return ROOT
