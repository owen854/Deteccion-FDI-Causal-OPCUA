"""Detector causal, método base, alineación en línea y evaluación (RF-33 a RF-38, RF-40, RF-41)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fdisim.causal.scm import PhysicsInformedSCM
from fdisim.common.config import load_config, load_scenario
from fdisim.common.paths import SCENARIOS_DIR
from fdisim.common.types import FT_101, LT_101, LT_102, P_101, PROCESS_TAGS
from fdisim.data.dataset import align_samples, label_grid
from fdisim.detection.causal_detector import CausalDetector
from fdisim.detection.isolation import isolate
from fdisim.detection.online_monitor import GridAligner
from fdisim.detection.pipeline import ALARM_COLUMNS, evaluate, run_detectors, summarize
from fdisim.detection.residuals import ResidualComputer, stream_names
from fdisim.detection.threshold_detector import ThresholdDetector
from fdisim.orchestration.offline import simulate_offline


@pytest.fixture(scope="module")
def config():
    return load_config().to_dict()


def _grid(config, scenario_name: str, seed: int, duration: float) -> tuple[pd.DataFrame, object]:
    scenario = load_scenario(SCENARIOS_DIR / f"{scenario_name}.yaml")
    result = simulate_offline(config, scenario, seed=seed, duration_s=duration)
    grid = label_grid(align_samples(result.samples, 0.5), result.events)
    return grid.assign(run_id=f"{scenario_name}-{seed}", scenario=scenario_name), result


@pytest.fixture(scope="module")
def normal(config):
    """Tres corridas normales offline de 800 s: entrenamiento, validación y prueba."""
    return {
        name: _grid(config, "normal", seed, 800.0)[0]
        for name, seed in (("train", 201), ("val", 202), ("test", 203))
    }


@pytest.fixture(scope="module")
def attacked(config):
    grid, result = _grid(config, "sesgo_lt102", 301, 1100.0)
    return grid, result


@pytest.fixture(scope="module")
def detectors(config, normal):
    scm = PhysicsInformedSCM.from_config(config).fit(normal["train"])
    causal = CausalDetector(config=config, scm=scm).fit((normal["train"], normal["val"]))
    base = ThresholdDetector.from_config(config).fit(normal["train"])
    return causal, base


def test_residuos_incrementales_coinciden_con_el_scm(config, normal):
    frame = normal["train"]
    scm = PhysicsInformedSCM.from_config(config).fit(frame)
    computer = ResidualComputer(scm, (20,))
    rows = [computer.update(v) for v in frame.to_dict("records")]
    streaming = pd.DataFrame(rows)
    expected = scm.residuals(frame)
    for tag in (LT_101, LT_102, P_101):
        np.testing.assert_allclose(
            streaming[f"{tag}:1"].to_numpy()[1:], expected[tag].to_numpy()[1:], atol=1e-9
        )
    # FT-101 tolera el instante de aplicación de la orden: nunca supera al residuo del SCM.
    tolerant = streaming[f"{FT_101}:1"].abs().to_numpy()[1:]
    assert np.all(tolerant <= expected[FT_101].abs().to_numpy()[1:] + 1e-9)
    k = 300  # gemelo en horizonte: observado − simulación desde k − 20
    history = {tag: frame[tag].to_numpy()[: k + 1].tolist() for tag in PROCESS_TAGS}
    twin = scm.simulate(history, 20)
    assert streaming[f"{LT_101}:20"].iloc[k] == pytest.approx(frame[LT_101].iloc[k] - twin[LT_101])
    assert streaming[f"{LT_102}:20"].iloc[k] == pytest.approx(frame[LT_102].iloc[k] - twin[LT_102])
    assert math.isnan(streaming[f"{LT_101}:20"].iloc[19])  # sin historia suficiente


def test_residuos_normalizados_en_validacion(detectors, normal):
    """RF-33: en validación normal, z de los residuos a un paso con media ≈ 0 y σ ≈ 1."""
    causal, _ = detectors
    raw = causal.residual_frame(normal["val"])
    for name in (f"{LT_101}:1", f"{LT_102}:1", f"{FT_101}:1"):
        mean, std = causal.stats[name]
        z = ((raw[name] - mean) / std).dropna()
        assert abs(z.mean()) < 0.2, name
        assert 0.8 < z.std() < 1.25, name


def test_calibracion_cumple_el_fpr_objetivo(detectors, normal):
    """RF-34: FPR medido en validación ≤ FPR objetivo (con retención de alarmas)."""
    causal, _ = detectors
    target = causal.settings["target_fpr"]
    assert causal.info["val_fpr"] <= target
    outputs = run_detectors(normal["val"], [causal])
    assert outputs.frames["causal"]["alarm"].mean() <= target + 1e-9
    assert set(causal.limits) == set(causal.decision_streams)
    assert "P-101:1" not in causal.limits  # informativo: no decide (ver causal_detector)


def test_detecta_e_identifica_el_sesgo_sobre_lt102(detectors, attacked):
    causal, base = detectors
    grid, _ = attacked
    outputs = run_detectors(grid, [causal, base])
    metrics = evaluate(grid, outputs)
    row = metrics[(metrics["detector"] == "causal") & (metrics["attack_id"] == "A1")].iloc[0]
    assert row["detected"] == 1.0
    assert row["delay_s"] < 30.0
    assert row["identified"] == LT_102
    summary = summarize(metrics)
    assert {"dr", "delay_mean_s", "fpr", "identification"} <= set(summary.columns)


def test_alarmas_registran_todos_los_campos(detectors, attacked):
    """RF-36: instante, detector, variables, tipo, severidad y estado."""
    causal, base = detectors
    outputs = run_detectors(attacked[0], [causal, base])
    alarms = outputs.alarms
    assert list(alarms.columns) == list(ALARM_COLUMNS)
    causal_alarms = alarms[alarms["detector"] == "causal"]
    assert len(causal_alarms) >= 1
    first = causal_alarms.iloc[0]
    assert first["kind"] in {"residual", "cusum", "ewma"}
    assert first["variables"] and first["suspected_tag"]
    assert set(alarms["state"]) <= {"active", "closed"}


def test_identificacion_por_firmas():
    assert isolate(set(), {}) is None
    assert isolate({LT_102}, {LT_102: 5.0}) == LT_102
    assert isolate({LT_101, LT_102}, {LT_101: 3.0, LT_102: 2.0}) == LT_101
    assert isolate({LT_101}, {LT_101: 4.0}) == LT_101
    assert isolate({FT_101, LT_101}, {FT_101: 6.0, LT_101: 2.0}) == FT_101
    # Actuador alterado con eco oculto: solo el caudal deja de cuadrar con la orden.
    assert isolate({FT_101, LT_102}, {FT_101: 8.0, LT_102: 1.1}) == P_101


def test_metodo_base_alarma_fuera_de_limites(config, normal):
    base = ThresholdDetector.from_config(config).fit(normal["train"])
    values = normal["train"].iloc[100][list(PROCESS_TAGS)].to_dict()
    assert not base.update(0.0, values).alarm
    out = base.update(0.5, {**values, LT_102: 49.0})  # fuera del límite operativo (45 cm)
    assert out.alarm and out.suspected_tag == LT_102
    assert out.alarms[0].kind.value == "limit"


def test_calibracion_persistente_reproduce_las_salidas(detectors, normal):
    causal, _ = detectors
    clone = CausalDetector(config={}, scm=causal.scm, calibration=causal.to_dict())
    a = run_detectors(normal["test"], [causal]).frames["causal"]
    b = run_detectors(normal["test"], [clone]).frames["causal"]
    pd.testing.assert_series_equal(a["alarm"], b["alarm"])
    np.testing.assert_allclose(a["max"], b["max"])


def test_alineador_en_linea_reproduce_la_rejilla_y_las_alarmas(detectors, attacked):
    """RF-38: alinear en línea y procesar = alinear la corrida guardada y reprocesar."""
    causal, base = detectors
    grid, result = attacked
    samples = result.samples.sort_values(["source_ts", "tag"])
    first = samples[samples["sim_time"] > 0].iloc[0]
    second = samples[samples["sim_time"] > first["sim_time"] + 1].iloc[0]
    scale = (second["sim_time"] - first["sim_time"]) / (second["source_ts"] - first["source_ts"])
    aligner = GridAligner(0.5, PROCESS_TAGS, time_scale=scale)
    aligner.on_clock(float(first["sim_time"]), float(first["source_ts"]))
    online = []
    for row in samples.itertuples():
        online.extend(aligner.push(row.tag, row.source_ts, row.value, row.status))
    offline = align_samples(result.samples, 0.5)
    n = min(len(online), len(offline)) - 1
    assert n > len(offline) - 3
    for i in (0, n // 2, n - 1):
        t, values = online[i]
        assert t == pytest.approx(offline["sim_time"].iloc[i])
        for tag in PROCESS_TAGS:
            assert values[tag] == pytest.approx(offline[tag].iloc[i])
    causal.reset()
    online_alarms = []
    for t, values in online[:n]:
        result_t = causal.update(t, values)
        online_alarms.extend(a.t for a in result_t.alarms if a.t_end is None)
    outputs = run_detectors(grid.iloc[:n], [causal])
    assert online_alarms == outputs.alarms["t"].tolist()


def test_nombres_de_residuos():
    assert stream_names((20, 120)) == (
        "LT-101:1",
        "LT-102:1",
        "FT-101:1",
        "P-101:1",
        "LT-101:20",
        "LT-102:20",
        "LT-101:120",
        "LT-102:120",
    )
