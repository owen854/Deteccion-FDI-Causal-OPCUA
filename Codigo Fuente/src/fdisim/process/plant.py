"""Planta completa: modelo + bomba + sensores + perturbaciones (RF-01 a RF-06).

En cada paso Δt: aplica el comando de la bomba, suma las perturbaciones vigentes, integra el
modelo y genera las mediciones. ``ground_truth`` produce el registro de verdad de terreno
(valores reales sin ruido) que viaja por el plano de experimento. La misma clase se usa en el
modo en red (detrás del servidor OPC UA) y en el modo offline (RF-38).

Reproducibilidad (RNF-08): cada sensor y el ruido de proceso usan flujos aleatorios
independientes derivados de la semilla de la corrida.

Implementado en la Fase 2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from fdisim.common.types import FT_101, FT_102, LT_101, LT_102, P_101, GroundTruthRecord
from fdisim.process.actuators import Pump, PumpParams
from fdisim.process.disturbances import DisturbanceSchedule
from fdisim.process.sensors import Sensor, SensorSpec
from fdisim.process.two_tank_model import TwoTankModel, TwoTankParams

SENSOR_RANGES: Mapping[str, tuple[float, float]] = {
    LT_101: (0.0, 50.0),
    LT_102: (0.0, 50.0),
    FT_101: (0.0, 150.0),
}


@dataclass(frozen=True, slots=True)
class PlantState:
    sim_time: float
    true_values: dict[str, float]  # h1, h2, q_in, q2 y u aplicados, sin ruido
    measured_values: dict[str, float]  # lo que publican los sensores (y el eco de P-101)


class Plant:
    def __init__(
        self,
        model: TwoTankModel,
        pump: Pump,
        sensors: dict[str, Sensor],
        disturbances: DisturbanceSchedule,
        dt_s: float,
        initial_levels_cm: tuple[float, float],
        rng: Any | None = None,
    ) -> None:
        if dt_s <= 0:
            raise ValueError("dt_s debe ser positivo")
        self.model = model
        self.pump = pump
        self.sensors = sensors
        self.disturbances = disturbances
        self.dt_s = dt_s
        self.initial_levels_cm = initial_levels_cm
        self.rng = rng if rng is not None else np.random.default_rng()
        self._k = 0
        self._h = initial_levels_cm
        self._q_in = 0.0

    @property
    def sim_time(self) -> float:
        return self._k * self.dt_s

    @property
    def levels(self) -> tuple[float, float]:
        return self._h

    def equilibrium_command(self, h2: float | None = None) -> float:
        """Comando de bomba que mantiene ``h2`` (por defecto el nivel inicial) en equilibrio."""
        level = self.initial_levels_cm[1] if h2 is None else h2
        return self.pump.command_for_flow(self.model.equilibrium_inflow(level))

    def reset(self, command_pct: float | None = None) -> PlantState:
        """Vuelve al estado inicial con la bomba en ``command_pct`` (equilibrio si se omite)."""
        self._k = 0
        self._h = self.initial_levels_cm
        self.pump.reset(self.equilibrium_command() if command_pct is None else command_pct)
        self._q_in = self.pump.params.gain_cm3_s_per_pct * self.pump.effective_pct
        return self._state()

    def step(self, command_pct: float) -> PlantState:
        """Avanza un paso Δt con el comando ``u`` vigente y devuelve el nuevo estado."""
        effects = self.disturbances.effects(self.sim_time)
        for tank in ("tank1", "tank2"):
            std = effects.pop(f"{tank}.noise_std", 0.0)
            if std > 0:
                effects[f"{tank}.extra_inflow"] = float(self.rng.normal(0.0, std))
        self._q_in = self.pump.apply(command_pct, self.dt_s)
        self._h = self.model.step(self._h, self._q_in, self.dt_s, effects)
        self._k += 1
        return self._state(effects)

    def _state(self, effects: Mapping[str, float] | None = None) -> PlantState:
        h1, h2 = self._h
        _, q2 = self.model.outflows(self._h, effects)
        true = {
            LT_101: h1,
            LT_102: h2,
            FT_101: self._q_in,
            FT_102: q2,
            P_101: self.pump.command_pct,
        }
        measured = {tag: sensor.measure(true[tag]) for tag, sensor in self.sensors.items()}
        measured[P_101] = self.pump.command_pct
        return PlantState(self.sim_time, true, measured)

    def ground_truth(
        self, state: PlantState, attack_active: bool = False, attack_id: str | None = None
    ) -> GroundTruthRecord:
        """Registro de verdad de terreno (RF-06) para el plano de experimento."""
        return GroundTruthRecord(
            state.sim_time,
            dict(state.true_values),
            dict(state.measured_values),
            attack_active,
            attack_id,
        )

    @classmethod
    def from_config(
        cls,
        plant: Mapping[str, Any],
        dt_s: float,
        seed: int | None = None,
        disturbances: DisturbanceSchedule | None = None,
        integrator: str = "solve_ivp",
    ) -> Plant:
        """Construye la planta desde la sección ``plant`` del YAML (RF-02)."""
        root = np.random.default_rng(seed)
        sensor_cfg: Mapping[str, Any] = plant.get("sensors", {})
        streams = root.spawn(len(sensor_cfg) + 1)
        sensors = {
            tag: Sensor(SensorSpec.from_config(tag, cfg, SENSOR_RANGES.get(tag)), stream)
            for (tag, cfg), stream in zip(sensor_cfg.items(), streams[:-1], strict=True)
        }
        initial = (
            float(plant["tank1"].get("initial_level_cm", 0.0)),
            float(plant["tank2"].get("initial_level_cm", 0.0)),
        )
        return cls(
            TwoTankModel(TwoTankParams.from_config(plant), integrator),
            Pump(PumpParams.from_config(plant["pump"])),
            sensors,
            disturbances or DisturbanceSchedule(),
            dt_s,
            initial,
            streams[-1],
        )
