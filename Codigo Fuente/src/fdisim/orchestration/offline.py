"""Ejecución offline: sin red, determinista y acelerada (RF-27, RF-38).

Fase 2: ``run_closed_loop`` encadena ``Plant`` → (transformación de la medición) →
``PIDController`` en un solo bucle de paso fijo. El PID se ejecuta cada ``Ts`` (múltiplo de
Δt) y su salida se mantiene entre muestras (retención de orden cero). El gancho
``measurement_transform`` es el punto donde, desde la Fase 4, el inyector FDI altera lo que ve
el controlador, igual que el gateway comprometido en el modo en red.

Fase 4: ``run_scenario_offline`` añadirá ataques, detectores y almacenamiento de la corrida.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common.config import ScenarioConfig
from fdisim.common.types import FT_101, FT_102, LT_101, LT_102, P_101
from fdisim.control.pid import PIDController, PIDParams
from fdisim.control.setpoint import SetpointProfile
from fdisim.process.disturbances import DisturbanceSchedule
from fdisim.process.plant import Plant

MeasurementTransform = Callable[[float, str, float], float]
TRUE_TAGS = (LT_101, LT_102, FT_101, FT_102, P_101)
MEASURED_TAGS = (LT_101, LT_102, FT_101, P_101)


@dataclass(slots=True)
class LoopResult:
    """Series de tiempo de una corrida en lazo cerrado (una muestra por paso Δt)."""

    t: np.ndarray
    true: dict[str, np.ndarray]
    measured: dict[str, np.ndarray]
    setpoint: np.ndarray
    command: np.ndarray
    step_compute_s: np.ndarray
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ClosedLoop:
    plant: Plant
    pid: PIDController
    setpoint: SetpointProfile
    controlled_tag: str = LT_102


def prepare_closed_loop(
    config: Mapping[str, Any],
    scenario: ScenarioConfig,
    seed: int | None = None,
    integrator: str | None = None,
    control_overrides: Mapping[str, float] | None = None,
) -> ClosedLoop:
    """Construye planta, PID y consigna desde ``default.yaml`` y un escenario."""
    sim = config["simulation"]
    plant = Plant.from_config(
        config["plant"],
        float(sim["dt_s"]),
        scenario.seed if seed is None else seed,
        DisturbanceSchedule.from_config(scenario.disturbances),
        integrator or str(sim.get("integrator", "solve_ivp")),
    )
    control = {**config["control"], **(control_overrides or {})}
    pid = PIDController(PIDParams.from_config(control))
    setpoint = SetpointProfile(scenario.setpoint_profile)
    return ClosedLoop(plant, pid, setpoint, str(control.get("controlled_tag", LT_102)))


def run_closed_loop(
    loop: ClosedLoop, duration_s: float, measurement_transform: MeasurementTransform | None = None
) -> LoopResult:
    plant, pid = loop.plant, loop.pid
    dt = plant.dt_s
    ratio = round(pid.params.ts_s / dt)
    if ratio < 1 or abs(ratio * dt - pid.params.ts_s) > 1e-9:
        raise ValueError("control.ts_s debe ser un múltiplo entero de simulation.dt_s")
    n = round(duration_s / dt)

    command = plant.equilibrium_command()
    state = plant.reset(command)
    pid.reset(initial_output=command)

    t = np.empty(n)
    sp_series = np.empty(n)
    u_series = np.empty(n)
    compute = np.empty(n)
    true = {tag: np.empty(n) for tag in TRUE_TAGS}
    measured = {tag: np.empty(n) for tag in MEASURED_TAGS}
    sp = loop.setpoint.value_at(0.0)
    for k in range(n):
        now = k * dt
        if k % ratio == 0:
            sp = loop.setpoint.value_at(now)
            y = state.measured_values[loop.controlled_tag]
            if measurement_transform is not None:
                y = measurement_transform(now, loop.controlled_tag, y)
            command = pid.update(sp, y)
        t0 = time.perf_counter()
        state = plant.step(command)
        compute[k] = time.perf_counter() - t0
        t[k] = state.sim_time
        sp_series[k] = sp
        u_series[k] = command
        for tag in TRUE_TAGS:
            true[tag][k] = state.true_values[tag]
        for tag in MEASURED_TAGS:
            measured[tag][k] = state.measured_values[tag]
    return LoopResult(
        t,
        true,
        measured,
        sp_series,
        u_series,
        compute,
        {"dt_s": dt, "ts_s": pid.params.ts_s, "integrator": plant.model.integrator},
    )


def run_scenario_offline(
    scenario_path: Path,
    config_path: Path | None = None,
    seed: int | None = None,
    overrides: dict | None = None,
) -> Path:
    """Ejecuta el escenario y devuelve la carpeta de la corrida (``data/raw/<run_id>``)."""
    raise NotImplementedError(
        "Fase 4 — RF-27/RF-38: ejecución offline con ataques y almacenamiento"
    )
