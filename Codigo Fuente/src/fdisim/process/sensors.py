"""Instrumentación simulada: sensores de nivel y caudal (RF-03).

Medición = valor real + sesgo de calibración + ruido gaussiano, cuantizada a la resolución
del instrumento y saturada en su rango. El generador aleatorio se recibe desde fuera para
garantizar la reproducibilidad por semilla (RNF-08).

Implementado en la Fase 2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdisim.common.config import ConfigError


@dataclass(frozen=True, slots=True)
class SensorSpec:
    tag: str
    noise_std: float
    resolution: float
    calibration_bias: float = 0.0
    range: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.noise_std < 0:
            raise ConfigError(
                f"plant.sensors.{self.tag}.noise_std: debe ser ≥ 0 ({self.noise_std})"
            )
        if self.resolution < 0:
            raise ConfigError(
                f"plant.sensors.{self.tag}.resolution: debe ser ≥ 0 ({self.resolution})"
            )

    @classmethod
    def from_config(
        cls, tag: str, cfg: Mapping[str, Any], range_: tuple[float, float] | None = None
    ) -> SensorSpec:
        return cls(
            tag,
            float(cfg.get("noise_std", 0.0)),
            float(cfg.get("resolution", 0.0)),
            float(cfg.get("calibration_bias", 0.0)),
            range_,
        )


class Sensor:
    def __init__(self, spec: SensorSpec, rng: Any) -> None:
        """``rng``: ``numpy.random.Generator`` propio del sensor (derivado de la semilla)."""
        self.spec = spec
        self.rng = rng

    def measure(self, true_value: float) -> float:
        s = self.spec
        value = true_value + s.calibration_bias
        if s.noise_std > 0:
            value += float(self.rng.normal(0.0, s.noise_std))
        if s.resolution > 0:
            value = round(value / s.resolution) * s.resolution
        if s.range is not None:
            value = min(max(value, s.range[0]), s.range[1])
        return float(value)
