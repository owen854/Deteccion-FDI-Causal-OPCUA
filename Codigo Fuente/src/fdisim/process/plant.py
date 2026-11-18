"""Planta completa: modelo + bomba + sensores + perturbaciones (RF-01 a RF-06).

En cada paso: aplica el comando de la bomba, integra el modelo, genera las mediciones y
emite la verdad de terreno por el plano de experimento. La misma clase se usa en el modo en
red (detrás del servidor OPC UA) y en el modo offline (RF-38).

Fase de implementación: Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdisim.common.types import GroundTruthRecord
from fdisim.process.actuators import Pump
from fdisim.process.disturbances import DisturbanceSchedule
from fdisim.process.sensors import Sensor
from fdisim.process.two_tank_model import TwoTankModel


@dataclass(frozen=True, slots=True)
class PlantState:
    sim_time: float
    true_values: dict[str, float]  # h1, h2, q_in, u sin ruido
    measured_values: dict[str, float]  # lo que publican los sensores


class Plant:
    def __init__(
        self,
        model: TwoTankModel,
        pump: Pump,
        sensors: dict[str, Sensor],
        disturbances: DisturbanceSchedule,
        dt_s: float,
        initial_levels_cm: tuple[float, float],
    ) -> None:
        self.model = model
        self.pump = pump
        self.sensors = sensors
        self.disturbances = disturbances
        self.dt_s = dt_s
        self.initial_levels_cm = initial_levels_cm

    def reset(self) -> PlantState:
        raise NotImplementedError("Fase 2 — RF-01: estado inicial")

    def step(self, command_pct: float) -> PlantState:
        """Avanza un paso Δt con el comando ``u`` vigente y devuelve el nuevo estado."""
        raise NotImplementedError("Fase 2 — RF-01/RF-03/RF-04: paso de la planta")

    def ground_truth(self, state: PlantState) -> GroundTruthRecord:
        """Convierte el estado en un registro de verdad de terreno (RF-06)."""
        raise NotImplementedError("Fase 3 — RF-06: verdad de terreno")
