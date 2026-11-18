"""Construcción de datasets de entrenamiento, validación y prueba (RF-27).

- Entrenamiento y validación: solo operación normal (con perturbaciones legítimas).
- Prueba: operación normal y escenarios con ataque, con etiquetas por muestra.
- Alineación: las muestras asíncronas se llevan a una rejilla uniforme de periodo
  ``detection.period_s`` (retención de orden cero), igual que en el monitor en línea.

Fase de implementación: Fase 4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def align_samples(samples: Any, period_s: float) -> Any:
    """Convierte la tabla de muestras en una tabla ancha (una columna por etiqueta) en rejilla."""
    raise NotImplementedError("Fase 4 — RF-27: alineación temporal")


def build_splits(run_dirs: list[Path], seed: int) -> dict[str, Any]:
    """Devuelve ``{"train": df, "val": df, "test": df}`` sin solapamiento temporal."""
    raise NotImplementedError("Fase 4 — RF-27: particiones")
