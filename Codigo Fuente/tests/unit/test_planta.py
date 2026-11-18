"""Criterios de aceptación de RF-02 a RF-04 y RF-06 (instrumentación, bomba, perturbaciones
y planta) y de RNF-01 (tiempo de cómputo por paso)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from fdisim.common import paths
from fdisim.common.config import ConfigError, load_yaml
from fdisim.common.types import FT_101, LT_101, LT_102, P_101
from fdisim.process.actuators import Pump, PumpParams
from fdisim.process.disturbances import Disturbance, DisturbanceSchedule
from fdisim.process.plant import Plant
from fdisim.process.sensors import Sensor, SensorSpec


@pytest.fixture(scope="module")
def plant_cfg():
    return load_yaml(paths.DEFAULT_CONFIG)["plant"]


def test_ruido_del_sensor_coincide_con_el_configurado():
    sensor = Sensor(SensorSpec("LT-102", noise_std=0.1, resolution=0.0), np.random.default_rng(1))
    samples = np.array([sensor.measure(25.0) for _ in range(20000)])
    assert samples.std() == pytest.approx(0.1, rel=0.10)
    assert samples.mean() == pytest.approx(25.0, abs=0.01)


def test_sensor_sesgo_cuantizacion_y_rango():
    sensor = Sensor(
        SensorSpec("LT-101", 0.0, 0.5, calibration_bias=0.2, range=(0.0, 50.0)),
        np.random.default_rng(0),
    )
    assert sensor.measure(10.1) == pytest.approx(10.5)
    assert sensor.measure(80.0) == 50.0
    with pytest.raises(ConfigError):
        SensorSpec("LT-101", -0.1, 0.01)


def test_bomba_saturada_y_con_dinamica():
    pump = Pump(PumpParams(1.5, time_constant_s=0.5))
    pump.reset(0.0)
    assert pump.apply(150.0, 0.1) < 150.0 * 1.5  # el actuador no responde instantáneamente
    for _ in range(100):
        q = pump.apply(150.0, 0.1)
    assert pump.command_pct == 100.0 and q == pytest.approx(150.0, rel=1e-3)
    pump.apply(-20.0, 0.1)
    assert pump.command_pct == 0.0
    with pytest.raises(ConfigError):
        PumpParams(0.0)


def test_perturbaciones_desde_el_escenario():
    schedule = DisturbanceSchedule.from_config(
        [
            {
                "type": "outlet_area",
                "target": "tank2",
                "t_s": 10,
                "duration_s": 5,
                "relative_change": 0.1,
            },
            {"type": "leak", "target": "tank1", "t_s": 12, "duration_s": 5, "flow_cm3_s": 2.0},
            {
                "type": "process_noise",
                "target": "tank1",
                "t_s": 0,
                "duration_s": 100,
                "std_cm3_s": 0.3,
            },
            {
                "type": "process_noise",
                "target": "tank1",
                "t_s": 0,
                "duration_s": 100,
                "std_cm3_s": 0.4,
            },
        ]
    )
    assert schedule.effects(5.0) == {"tank1.noise_std": pytest.approx(0.5)}
    effects = schedule.effects(13.0)
    assert effects["tank2.outlet_scale"] == pytest.approx(1.1)
    assert effects["tank1.leak"] == pytest.approx(2.0)
    assert "tank2.outlet_scale" not in schedule.effects(15.0)
    with pytest.raises(ConfigError):
        Disturbance.from_config(
            {"type": "leak", "target": "tank3", "t_s": 0, "duration_s": 1, "flow_cm3_s": 1}
        )
    with pytest.raises(ConfigError):
        Disturbance.from_config({"type": "leak", "target": "tank1", "t_s": 0, "duration_s": 1})


def test_planta_en_equilibrio_y_verdad_de_terreno(plant_cfg):
    plant = Plant.from_config(plant_cfg, dt_s=0.1, seed=3)
    state = plant.reset()
    for _ in range(600):
        state = plant.step(plant.equilibrium_command())
    assert state.sim_time == pytest.approx(60.0)
    assert state.true_values[LT_102] == pytest.approx(25.0, abs=0.05)
    assert set(state.measured_values) == {LT_101, LT_102, FT_101, P_101}
    record = plant.ground_truth(state, attack_active=True, attack_id="A1")
    assert record.true_values[LT_102] == state.true_values[LT_102] and record.attack_id == "A1"


def test_misma_semilla_misma_corrida(plant_cfg):
    def run(seed):
        plant = Plant.from_config(plant_cfg, 0.1, seed)
        plant.reset()
        return [plant.step(60.0).measured_values[LT_102] for _ in range(200)]

    assert run(5) == run(5)
    assert run(5) != run(6)


def test_rnf01_computo_por_paso(plant_cfg):
    plant = Plant.from_config(plant_cfg, dt_s=0.1, seed=0)
    plant.reset()
    durations = []
    for _ in range(2000):
        t0 = time.perf_counter()
        plant.step(60.0)
        durations.append(time.perf_counter() - t0)
    assert np.percentile(durations, 99) < 0.1 * 0.1  # < 10 % de Δt
