"""Instrumentación simulada: sensores de nivel y caudal (RF-03).

Medición = valor real + sesgo de calibración + ruido gaussiano, cuantizada a la resolución
del instrumento. El generador aleatorio se recibe desde fuera para garantizar la
reproducibilidad por semilla (RNF-08).

Fase de implementación: Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SensorSpec:
    tag: str
    noise_std: float
    resolution: float
    calibration_bias: float = 0.0


class Sensor:
    def __init__(self, spec: SensorSpec, rng: Any) -> None:
        """``rng``: ``numpy.random.Generator`` derivado de la semilla de la corrida."""
        self.spec = spec
        self.rng = rng

    def measure(self, true_value: float) -> float:
        raise NotImplementedError("Fase 2 — RF-03: ruido, sesgo y cuantización")
