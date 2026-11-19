"""Modo offline con ataques (RF-38), datasets reproducibles (RF-27) y apoyo de la HMI (RF-23)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fdisim.common.config import ConfigError, load_config, load_scenario
from fdisim.common.experiment_channel import ExperimentClient, ExperimentServer
from fdisim.common.paths import SCENARIOS_DIR
from fdisim.common.types import LT_102, P_101
from fdisim.data.dataset import align_samples, generate_datasets, label_grid
from fdisim.data.storage import verify_run
from fdisim.orchestration.offline import run_scenario_offline, simulate_offline
from fdisim.orchestration.run_summary import summarize_offline_run
from fdisim.orchestration.runtime import interactive_attack
from fdisim.ui.pages.experiments import attack_request, attack_rows


def scenario_file(tmp_path: Path, name: str, attacks: str, duration: float = 60.0) -> Path:
    path = tmp_path / f"{name}.yaml"
    base = (SCENARIOS_DIR / "normal.yaml").as_posix()
    path.write_text(
        f"name: {name}\nbase: {base}\nseed: 3\nduration_s: {duration}\nattacks:\n{attacks}",
        encoding="utf-8",
    )
    return path


BIAS = """  - id: A1
    type: bias
    targets: [LT-102]
    start_s: 20
    duration_s: 20
    params: { bias: 2.0 }
    stealth: { enabled: true, envelope: [2.0, 45.0], max_rate_per_s: 0.5 }
"""
ACTUATOR = """  - id: A1
    type: bias
    targets: [P-101]
    start_s: 20
    duration_s: 20
    params: { bias: 8.0 }
    stealth: { enabled: false }
"""


def test_offline_con_sesgo_cumple_los_criterios(tmp_path):
    scenario = load_scenario(scenario_file(tmp_path, "sesgo_corto", BIAS))
    config = load_config().to_dict()
    result = simulate_offline(config, scenario, duration_s=60.0)
    assert len(result.ground_truth) == 600
    summary = summarize_offline_run(result, config, scenario, 3, 60.0)
    effect = summary["attack_effects"][0]
    assert effect["median_diff"] == pytest.approx(2.0) and effect["ok"]
    for name in (
        "RF-16 transparente fuera de las ventanas de ataque",
        "RF-17 sesgo recibido = b",
        "RF-20 valores falsos dentro de la envolvente",
        "RF-21 primer valor falso ≤ 1 periodo tras el inicio",
    ):
        assert summary["criteria"][name] is True, name
    gt = result.ground_truth
    assert gt.loc[gt["attack_active"], "sim_time"].agg(["min", "max"]).tolist() == pytest.approx(
        [20.0, 39.9]
    )


def test_ataque_al_actuador_queda_oculto_para_los_clientes(tmp_path):
    scenario = load_scenario(scenario_file(tmp_path, "actuador_corto", ACTUATOR))
    result = simulate_offline(load_config().to_dict(), scenario, duration_s=60.0)
    gt, samples = result.ground_truth, result.samples
    written = samples[(samples["tag"] == P_101) & (samples["sim_time"] == 30.0)]["value"].iloc[0]
    applied = gt.loc[np.isclose(gt["sim_time"], 30.1), f"meas_{P_101}"].iloc[0]
    assert applied - written == pytest.approx(8.0)  # la planta recibe la orden alterada


def test_corrida_offline_es_reproducible(tmp_path):
    path = scenario_file(tmp_path, "sesgo_corto", BIAS)
    first = verify_run(run_scenario_offline(path, raw_dir=tmp_path / "a", run_id="r"))
    second = verify_run(run_scenario_offline(path, raw_dir=tmp_path / "b", run_id="r"))
    for name in ("samples.parquet", "ground_truth.parquet", "attacks.parquet"):
        assert first.files_sha256[name] == second.files_sha256[name], name


def test_alineacion_en_rejilla_y_etiquetas(tmp_path):
    scenario = load_scenario(scenario_file(tmp_path, "sesgo_corto", BIAS))
    result = simulate_offline(load_config().to_dict(), scenario, duration_s=60.0)
    grid = label_grid(align_samples(result.samples, 0.5), result.events)
    assert grid["sim_time"].iloc[0] == 0.0 and grid["sim_time"].diff().dropna().eq(0.5).all()
    assert not grid[["LT-101", "LT-102", "FT-101", "P-101", "LIC-102.SP"]].isna().any().any()
    attacked = grid.loc[grid["label"] == 1, "sim_time"]
    assert attacked.min() == 20.0 and attacked.max() == 39.5
    assert grid["atk_LT-102"].sum() == grid["label"].sum() and grid["atk_LT-101"].sum() == 0


def test_datasets_v1_reproducibles_y_sin_solapamiento(tmp_path):
    attack = scenario_file(tmp_path, "sesgo_corto", BIAS)
    kwargs = dict(
        normal_scenario=SCENARIOS_DIR / "normal.yaml",
        attack_scenarios=[attack],
        n_train=2,
        n_val=1,
        n_test_normal=1,
        n_per_attack=1,
        base_seed=50,
        duration_s=30.0,
    )
    m1 = json.loads(generate_datasets(tmp_path / "d1", **kwargs).read_text(encoding="utf-8"))
    m2 = json.loads(generate_datasets(tmp_path / "d2", **kwargs).read_text(encoding="utf-8"))
    assert m1["files_sha256"] == m2["files_sha256"]  # misma semilla → archivos idénticos
    assert [r["seed"] for r in m1["runs"]] == [50, 51, 52, 53, 1050]
    train = pd.read_parquet(tmp_path / "d1" / "train.parquet")
    test = pd.read_parquet(tmp_path / "d1" / "test.parquet")
    assert train["label"].sum() == 0 and test["label"].sum() > 0
    assert set(train["run_id"]).isdisjoint(set(test["run_id"]))


def test_ataque_interactivo_validado():
    spec = interactive_attack(
        {"type": "ramp", "targets": [LT_102], "params": {"slope_per_s": 0.01}}, "HMI-1"
    )
    assert spec.attack_id == "HMI-1" and spec.duration_s == 300.0
    with pytest.raises(ValueError):
        interactive_attack({"type": "bias", "targets": [LT_102], "params": {}}, "HMI-2")
    with pytest.raises(ConfigError):
        interactive_attack({"type": "bias", "targets": ["XX-1"], "params": {"bias": 1}}, "HMI-3")


def test_formulario_y_tabla_de_la_pagina_de_experimentos():
    request = attack_request("bias", LT_102, 60, bias=1.5)
    assert request["params"] == {"bias": 1.5} and request["stealth"]["envelope"] == [2.0, 45.0]
    assert attack_request("replay", LT_102, 60)["stealth"] == {"enabled": False}
    status = {
        "sim_time": 950.0,
        "scenario_attacks": [
            {
                "id": "A1",
                "type": "bias",
                "targets": [LT_102],
                "start_s": 900,
                "duration_s": 300,
                "params": {"bias": 2.0},
            }
        ],
        "events": [
            {
                "attack_id": "HMI-1",
                "type": "ramp",
                "targets": [LT_102],
                "t_start": 100.0,
                "t_end": 160.0,
                "params": {"slope_per_s": 0.01},
            }
        ],
    }
    rows = {r["id"]: r for r in attack_rows(status)}
    assert rows["A1"]["estado"] == "activo" and rows["HMI-1"]["estado"] == "terminado"


def test_canal_de_experimento_autenticado():
    server = ExperimentServer(lambda msg: {"ok": True, "echo": msg["cmd"]})
    server.start()
    try:
        host, port = server.address
        client = ExperimentClient((host, port), server.authkey)
        assert client.status() == {"ok": True, "echo": "status"}
        intruder = ExperimentClient((host, port), b"clave-incorrecta")
        assert intruder.status()["ok"] is False
    finally:
        server.close()
