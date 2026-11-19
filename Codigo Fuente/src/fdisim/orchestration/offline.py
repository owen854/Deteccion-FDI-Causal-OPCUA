"""Ejecución offline: sin red, determinista y acelerada (RF-27, RF-38).

Fase 2: ``run_closed_loop`` encadena ``Plant`` → (transformación de la medición) →
``PIDController`` en un solo bucle de paso fijo. El PID se ejecuta cada ``Ts`` (múltiplo de
Δt) y su salida se mantiene entre muestras (retención de orden cero).

Fase 4: ``simulate_offline`` reproduce sin red la misma cadena que el modo en red, con el
**mismo** ``FdiInjector`` que usa el gateway:

    planta → inyector (mediciones) → controlador y «monitor»
    controlador → inyector (órdenes, RF-24) → planta

El «monitor» offline registra exactamente lo que publicaría el gateway: cada paso de LT-101,
LT-102 y FT-101, cada orden P-101 que escribe el controlador y cada cambio de consigna. Las
marcas de tiempo son el tiempo simulado, así que no hay ningún dato de reloj de pared y la
misma semilla produce archivos idénticos (RF-27, RNF-08). ``run_scenario_offline`` guarda la
corrida con el mismo formato que el modo en red.
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


@dataclass(slots=True)
class OfflineRun:
    """Resultado de ``simulate_offline`` con las mismas tablas que una corrida en red."""

    samples: Any  # DataFrame: tag, value, source_ts, server_ts, received_ts, status, sim_time…
    ground_truth: Any  # DataFrame: sim_time, source_ts, true_*, meas_*, attack_active, attack_id
    events: list  # AttackEvent ejecutados
    stats: dict[str, Any] = field(default_factory=dict)


def simulate_offline(
    config: Mapping[str, Any],
    scenario: ScenarioConfig,
    seed: int | None = None,
    duration_s: float | None = None,
    integrator: str | None = None,
) -> OfflineRun:
    """Simula el escenario completo (con ataques) sin red y devuelve sus tablas."""
    import pandas as pd

    from fdisim.attacks.injector import FdiInjector
    from fdisim.attacks.scheduler import AttackScheduler
    from fdisim.common.types import SP_102
    from fdisim.data.labels import label_ground_truth, label_samples

    loop = prepare_closed_loop(config, scenario, seed=seed, integrator=integrator)
    plant, pid, profile = loop.plant, loop.pid, loop.setpoint
    dt = plant.dt_s
    ratio = round(pid.params.ts_s / dt)
    if ratio < 1 or abs(ratio * dt - pid.params.ts_s) > 1e-9:
        raise ValueError("control.ts_s debe ser un múltiplo entero de simulation.dt_s")
    steps = round(float(duration_s or scenario.duration_s) / dt)
    injector = FdiInjector(AttackScheduler(list(scenario.attacks)))

    client_command = plant.equilibrium_command()
    state = plant.reset(client_command)
    pid.reset(initial_output=client_command)
    plant_command = client_command
    setpoint = profile.value_at(0.0)

    tags: list[str] = []
    values: list[float] = []
    times: list[float] = []

    def publish(tag: str, value: float, t: float) -> None:
        tags.append(tag)
        values.append(value)
        times.append(t)

    latest = {}
    for tag in (LT_101, LT_102, FT_101):
        latest[tag] = injector.process(tag, state.measured_values[tag], 0.0)
        publish(tag, latest[tag], 0.0)
    publish(SP_102, setpoint, 0.0)

    gt_rows: list[dict[str, float]] = []
    started = time.perf_counter()
    for k in range(steps):
        t_now = round(k * dt, 6)
        if k % ratio == 0:
            new_setpoint = profile.value_at(t_now)
            if new_setpoint != setpoint:
                setpoint = new_setpoint
                publish(SP_102, setpoint, t_now)
            client_command = pid.update(setpoint, latest[loop.controlled_tag])
            plant_command = injector.process_command(P_101, client_command, t_now)
            publish(P_101, client_command, t_now)  # el gateway muestra la orden del cliente
        state = plant.step(plant_command)
        t = state.sim_time
        for tag in (LT_101, LT_102, FT_101):
            latest[tag] = injector.process(tag, state.measured_values[tag], t)
            publish(tag, latest[tag], t)
        row = {"sim_time": t, "source_ts": t}
        row.update({f"true_{tag}": v for tag, v in state.true_values.items()})
        row[f"true_{SP_102}"] = setpoint
        row.update({f"meas_{tag}": v for tag, v in state.measured_values.items()})
        row[f"meas_{SP_102}"] = setpoint
        gt_rows.append(row)
    elapsed = time.perf_counter() - started

    stamps = np.asarray(times, dtype=float)
    samples = pd.DataFrame(
        {
            "tag": tags,
            "value": np.asarray(values, dtype=float),
            "source_ts": stamps,
            "server_ts": stamps,
            "received_ts": stamps,
            "status": "Good",
            "sim_time": stamps,
        }
    )
    events = injector.events()
    samples = label_samples(samples, events)
    ground_truth = label_ground_truth(pd.DataFrame(gt_rows), events)
    simulated = steps * dt
    return OfflineRun(
        samples,
        ground_truth,
        events,
        {
            "steps": steps,
            "dt_s": dt,
            "integrator": plant.model.integrator,
            "wall_s": elapsed,
            "speedup": simulated / elapsed if elapsed > 0 else float("inf"),
            "falsified_values": injector.falsified,
        },
    )


def run_scenario_offline(
    scenario_path: Path,
    config_path: Path | None = None,
    seed: int | None = None,
    overrides: dict | None = None,
    *,
    duration_s: float | None = None,
    integrator: str | None = None,
    raw_dir: Path | None = None,
    run_id: str | None = None,
) -> Path:
    """Ejecuta el escenario offline y devuelve la carpeta de la corrida (``data/raw/<run_id>``).

    Guarda las mismas tablas que el modo en red (más ``attacks``), la configuración efectiva,
    el escenario resuelto, el resumen y el manifiesto con los SHA-256 (RF-26, RF-27).
    """
    import json
    from datetime import datetime

    from fdisim.common import paths
    from fdisim.common.config import load_config, load_scenario
    from fdisim.common.types import RunManifest, RunMode
    from fdisim.data.labels import events_frame
    from fdisim.data.storage import (
        finalize_run,
        git_commit,
        new_run_id,
        package_versions,
        sha256_text,
    )
    from fdisim.orchestration.run_summary import summarize_offline_run
    from fdisim.orchestration.runtime import write_run_inputs

    config = load_config(config_path, overrides).to_dict()
    scenario = load_scenario(scenario_path)
    seed = scenario.seed if seed is None else int(seed)
    duration = float(duration_s or scenario.duration_s)
    run_id = run_id or new_run_id(f"{scenario.name}_s{seed}_offline")
    base = Path(raw_dir) if raw_dir else paths.resolve(config["data"].get("raw_dir", paths.RAW_DIR))
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    result = simulate_offline(config, scenario, seed, duration, integrator)
    fmt = str(config["data"]["format"])
    tables = {
        "samples": result.samples,
        "ground_truth": result.ground_truth,
        "attacks": events_frame(result.events),
    }
    for name, frame in tables.items():
        target = run_dir / f"{name}.{fmt}"
        if fmt == "parquet":
            frame.to_parquet(target, index=False)
        else:
            frame.to_csv(target, index=False)
    config_text = write_run_inputs(run_dir, config, scenario, seed, duration)
    summary = summarize_offline_run(result, config, scenario, seed, duration)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    finalize_run(
        run_dir,
        RunManifest(
            run_id=run_id,
            scenario=scenario.name,
            seed=seed,
            mode=RunMode.OFFLINE,
            started_at=started_at,
            git_commit=git_commit(),
            config_sha256=sha256_text(config_text),
            package_versions=package_versions(),
        ),
    )
    return run_dir
