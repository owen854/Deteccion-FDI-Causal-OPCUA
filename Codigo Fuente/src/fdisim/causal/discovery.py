"""Descubrimiento causal a partir de datos de operación normal (RF-29).

- PCMCI / PCMCI+ (tigramite): prueba de independencia ParCorr (lineal) y, opcionalmente,
  una no lineal; parámetros ``tau_max`` y ``alpha``.
- Causalidad de Granger (statsmodels): pruebas por pares y condicionales sobre un VAR.

Ambos devuelven una lista homogénea de enlaces con retardo y valor p, para compararlos con
el grafo físico en ``graph_compare`` (estudio comparativo, actividad 3.1).

Se ejecuta fuera de línea (riesgo R5): la detección en línea usa el SCM ya ajustado.
Fase de implementación: Fase 5. Dependencias previstas: tigramite, statsmodels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscoveredLink:
    source: str
    target: str
    lag: int
    p_value: float
    strength: float  # p. ej. correlación parcial (PCMCI) o estadístico F (Granger)
    method: str


def run_pcmci(
    data: Any, tau_max: int = 5, alpha: float = 0.01, ci_test: str = "parcorr", plus: bool = True
) -> list[DiscoveredLink]:
    raise NotImplementedError("Fase 5 — RF-29: PCMCI/PCMCI+ con tigramite")


def run_granger(data: Any, max_lag: int = 5, alpha: float = 0.01) -> list[DiscoveredLink]:
    raise NotImplementedError("Fase 5 — RF-29: causalidad de Granger con statsmodels")
