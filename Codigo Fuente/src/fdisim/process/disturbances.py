"""Perturbaciones operacionales legítimas (RF-04).

Eventos programados por escenario que **no** son ataques: cambio del área de descarga
(válvula manual), fugas pequeñas y ruido de proceso. Sirven para comprobar que el detector
distingue un ataque de un cambio operacional normal (control de falsos positivos, riesgo R4).

Fase de implementación: Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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

    def is_active(self, t: float) -> bool:
        return self.t_s <= t < self.t_s + self.duration_s


class DisturbanceSchedule:
    def __init__(self, disturbances: list[Disturbance]) -> None:
        self.disturbances = disturbances

    def active(self, t: float) -> list[Disturbance]:
        return [d for d in self.disturbances if d.is_active(t)]

    def effects(self, t: float) -> dict[str, float]:
        """Efecto agregado en el instante ``t`` (p. ej. ``{"tank2.outlet_scale": 1.1}``)."""
        raise NotImplementedError("Fase 2 — RF-04: efecto de perturbaciones")
