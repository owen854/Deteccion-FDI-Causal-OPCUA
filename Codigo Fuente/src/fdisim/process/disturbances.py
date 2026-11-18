"""Perturbaciones operacionales legítimas (RF-04).

Eventos programados por escenario que **no** son ataques: cambio del área de descarga
(válvula manual), fugas pequeñas y ruido de proceso. Sirven para comprobar que el detector
distingue un ataque de un cambio operacional normal (control de falsos positivos, riesgo R4).

Formato en el escenario YAML::

    disturbances:
      - { type: outlet_area,   target: tank2, t_s: 900,  duration_s: 120, relative_change: 0.10 }
      - { type: leak,          target: tank1, t_s: 1500, duration_s: 60,  flow_cm3_s: 2.0 }
      - { type: process_noise, target: tank1, t_s: 0,    duration_s: 1800, std_cm3_s: 0.5 }

Implementado en la Fase 2.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdisim.common.config import ConfigError

TARGETS = ("tank1", "tank2")
_MAGNITUDE_KEYS = {
    "outlet_area": "relative_change",
    "leak": "flow_cm3_s",
    "process_noise": "std_cm3_s",
}


class DisturbanceType(StrEnum):
    OUTLET_AREA = "outlet_area"  # cambio relativo del área de descarga
    LEAK = "leak"  # caudal de fuga [cm³/s]
    PROCESS_NOISE = "process_noise"  # ruido en el caudal [cm³/s]


@dataclass(frozen=True, slots=True)
class Disturbance:
    type: DisturbanceType
    target: str  # tank1 | tank2
    t_s: float
    duration_s: float
    magnitude: float

    def __post_init__(self) -> None:
        if self.target not in TARGETS:
            raise ConfigError(f"disturbances.target: use {TARGETS} (valor: {self.target})")
        if self.duration_s <= 0:
            raise ConfigError(f"disturbances.duration_s: debe ser positiva ({self.duration_s})")
        if self.type is DisturbanceType.OUTLET_AREA and self.magnitude <= -1:
            raise ConfigError("disturbances.relative_change: debe ser > -1")
        if self.type is not DisturbanceType.OUTLET_AREA and self.magnitude < 0:
            raise ConfigError(f"disturbances.{_MAGNITUDE_KEYS[self.type]}: debe ser ≥ 0")

    def is_active(self, t: float) -> bool:
        return self.t_s <= t < self.t_s + self.duration_s

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> Disturbance:
        try:
            kind = DisturbanceType(cfg["type"])
        except (KeyError, ValueError):
            raise ConfigError(
                f"disturbances.type: use {[t.value for t in DisturbanceType]}"
            ) from None
        key = _MAGNITUDE_KEYS[kind.value]
        magnitude = cfg.get(key, cfg.get("magnitude"))
        if magnitude is None:
            raise ConfigError(f"disturbances.{key}: campo obligatorio para '{kind.value}'")
        return cls(
            kind,
            str(cfg.get("target", "")),
            float(cfg.get("t_s", 0.0)),
            float(cfg.get("duration_s", 0.0)),
            float(magnitude),
        )


class DisturbanceSchedule:
    def __init__(self, disturbances: Iterable[Disturbance] = ()) -> None:
        self.disturbances = list(disturbances)

    @classmethod
    def from_config(cls, items: Iterable[Mapping[str, Any]]) -> DisturbanceSchedule:
        return cls(Disturbance.from_config(item) for item in items)

    def active(self, t: float) -> list[Disturbance]:
        return [d for d in self.disturbances if d.is_active(t)]

    def effects(self, t: float) -> dict[str, float]:
        """Efecto agregado en ``t``: ``<tanque>.outlet_scale`` (producto), ``<tanque>.leak``
        (suma) y ``<tanque>.noise_std`` (raíz de la suma de varianzas)."""
        effects: dict[str, float] = {}
        variances: dict[str, float] = {}
        for d in self.active(t):
            if d.type is DisturbanceType.OUTLET_AREA:
                key = f"{d.target}.outlet_scale"
                effects[key] = effects.get(key, 1.0) * (1.0 + d.magnitude)
            elif d.type is DisturbanceType.LEAK:
                key = f"{d.target}.leak"
                effects[key] = effects.get(key, 0.0) + d.magnitude
            else:
                variances[d.target] = variances.get(d.target, 0.0) + d.magnitude**2
        for target, var in variances.items():
            effects[f"{target}.noise_std"] = math.sqrt(var)
        return effects
