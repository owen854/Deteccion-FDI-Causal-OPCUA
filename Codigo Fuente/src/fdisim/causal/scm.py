"""Modelo causal estructural (SCM) del proceso (RF-31).

Cada variable endógena se predice a partir de sus padres causales observados:

- **Físico-informado:** balances de masa discretizados, con ``a1``, ``a2`` y ``k_p``
  identificados por mínimos cuadrados sobre datos normales::

      h1(t) = h1(t−1) + Δt/A1 · [q_in(t−1) − a1·√(2g·h1(t−1))]
      h2(t) = h2(t−1) + Δt/A2 · [a1·√(2g·h1(t−1)) − a2·√(2g·h2(t−1))]
      q_in(t) = k_p · u(t)

- **Por regresión:** modelo lineal o no lineal (scikit-learn) sobre los padres con retardo.

Además de la predicción a un paso, ``simulate`` propaga el modelo en un horizonte H usando
sus propias predicciones para las variables de estado y las observaciones para las
entradas exógenas (gemelo causal), lo que hace visibles las desviaciones lentas (rampas).

Fase de implementación: Fase 5. Dependencias previstas: NumPy, SciPy, scikit-learn.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResidualStats:
    mean: float
    std: float


class StructuralCausalModel(ABC):
    @abstractmethod
    def fit(self, normal_data: Any) -> StructuralCausalModel:
        """Ajusta las ecuaciones y estima ``residual_stats`` en datos normales."""

    @abstractmethod
    def predict_one_step(self, history: Mapping[str, list[float]]) -> dict[str, float]:
        """Predicción de cada variable endógena a partir de los padres observados."""

    @abstractmethod
    def simulate(self, history: Mapping[str, list[float]], horizon: int) -> dict[str, float]:
        """Predicción en horizonte ``horizon`` (residuo multi-paso, RF-33)."""

    residual_stats: dict[str, ResidualStats]


class PhysicsInformedSCM(StructuralCausalModel):
    def fit(self, normal_data: Any) -> PhysicsInformedSCM:
        raise NotImplementedError("Fase 5 — RF-31: identificación de parámetros físicos")

    def predict_one_step(self, history: Mapping[str, list[float]]) -> dict[str, float]:
        raise NotImplementedError("Fase 5 — RF-31")

    def simulate(self, history: Mapping[str, list[float]], horizon: int) -> dict[str, float]:
        raise NotImplementedError("Fase 6 — RF-33: gemelo causal multi-paso")


class RegressionSCM(StructuralCausalModel):
    def fit(self, normal_data: Any) -> RegressionSCM:
        raise NotImplementedError("Fase 5 — RF-31: ecuaciones por regresión")

    def predict_one_step(self, history: Mapping[str, list[float]]) -> dict[str, float]:
        raise NotImplementedError("Fase 5 — RF-31")

    def simulate(self, history: Mapping[str, list[float]], horizon: int) -> dict[str, float]:
        raise NotImplementedError("Fase 6 — RF-33")
