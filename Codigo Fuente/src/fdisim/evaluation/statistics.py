"""Análisis estadístico y de sensibilidad (RF-44, RF-45).

- Prueba de Wilcoxon de rangos con signo, pareada por repetición, entre el detector causal y
  el método base, para cada métrica y escenario.
- Intervalos de confianza por bootstrap.
- Curvas de sensibilidad: DR y retardo frente a la magnitud del sesgo o la pendiente de la rampa.

Fase de implementación: Fase 8. Dependencias previstas: SciPy, pandas.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def paired_wilcoxon(causal: Sequence[float], baseline: Sequence[float]) -> tuple[float, float]:
    """Devuelve ``(estadístico, valor_p)``."""
    raise NotImplementedError("Fase 8 — RF-45: prueba de Wilcoxon")


def bootstrap_ci(
    values: Sequence[float], confidence: float = 0.95, n_boot: int = 2000, seed: int = 0
) -> tuple[float, float]:
    raise NotImplementedError("Fase 8 — RF-45: intervalos de confianza")


def sensitivity_curve(results: Any, factor: str, metric: str) -> Any:
    raise NotImplementedError("Fase 8 — RF-45: curvas de sensibilidad")
