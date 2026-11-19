"""Configuración global (RF-53), historiador (RF-25) y corridas con manifiesto (RF-26)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from fdisim.common.config import ConfigError, deep_merge, load_config
from fdisim.common.types import GroundTruthRecord, RunManifest, RunMode, Sample
from fdisim.data.historian import Historian
from fdisim.data.storage import (
    finalize_run,
    new_run_id,
    read_run,
    sha256_file,
    verify_run,
    write_run,
)


def test_configuracion_por_defecto_valida():
    cfg = load_config()
    assert cfg.opcua["security"]["mode"] == "SignAndEncrypt"
    assert set(cfg.to_dict()) >= {"simulation", "plant", "control", "opcua", "data", "ui"}


def test_archivo_parcial_se_combina_con_los_valores_por_defecto(tmp_path):
    override = tmp_path / "mi.yaml"
    override.write_text("simulation:\n  time_scale: 5\n", encoding="utf-8")
    cfg = load_config(override)
    assert cfg.simulation["time_scale"] == 5
    assert cfg.simulation["dt_s"] == 0.1  # valor por defecto conservado
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {"a": {"b": 3, "c": 2}}


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"simulation": {"dt_s": -1}}, "simulation.dt_s"),
        ({"simulation": {"mode": "magico"}}, "simulation.mode"),
        ({"plant": {"tank1": {"area_cm2": 0}}}, "plant.tank1.area_cm2"),
        ({"control": {"ts_s": 0.25}}, "control.ts_s"),
        ({"control": {"setpoint_cm": 60}}, "control.setpoint_cm"),
        ({"opcua": {"host": "8.8.8.8"}}, "opcua.host"),
        ({"opcua": {"gateway": {"port": 4840}}}, "opcua.gateway.port"),
        ({"opcua": {"security": {"policy": "Basic128Rsa15"}}}, "opcua.security"),
        ({"opcua": {"security": {"mode": "None"}}}, "opcua.security"),
        ({"data": {"format": "xls"}}, "data.format"),
        ({"logging": {"level": "TODO"}}, "logging.level"),
    ],
)
def test_configuracion_invalida_indica_el_campo(override, field):
    with pytest.raises(ConfigError, match=f"^{field}"):
        load_config(overrides=override)


def _sample(i: int) -> Sample:
    return Sample("LT-102", 25.0 + i, 100.0 + i, 100.05 + i, 100.1 + i, "Good")


def _gt(i: int, attack_id=None) -> GroundTruthRecord:
    return GroundTruthRecord(
        0.1 * (i + 1),
        {"LT-102": 25.0, "P-101": 59.0},
        {"LT-102": 25.0 + i, "P-101": 59.0},
        attack_active=attack_id is not None,
        attack_id=attack_id,
        source_ts=100.0 + i,
    )


@pytest.mark.parametrize("fmt", ["parquet", "csv"])
def test_historiador_vuelca_por_bloques_y_conserva_marcas_de_tiempo(tmp_path, fmt):
    historian = Historian(tmp_path, flush_every=3, fmt=fmt)
    for i in range(7):
        historian.record_sample(_sample(i))
        historian.record_ground_truth(_gt(i, "A1" if i == 5 else None))
    historian.close()
    historian.close()  # segunda llamada inofensiva
    reader = pd.read_parquet if fmt == "parquet" else pd.read_csv
    samples = reader(tmp_path / f"samples.{fmt}")
    gt = reader(tmp_path / f"ground_truth.{fmt}")
    assert len(samples) == 7 and len(gt) == 7
    assert list(samples.columns) == [
        "tag",
        "value",
        "source_ts",
        "server_ts",
        "received_ts",
        "status",
    ]
    assert {"true_LT-102", "meas_LT-102", "attack_active", "attack_id"} <= set(gt.columns)
    assert gt["attack_active"].sum() == 1
    assert historian.counts["samples"] == 7
    with pytest.raises(RuntimeError):
        historian.record_sample(_sample(0))


def _manifest() -> RunManifest:
    return RunManifest("r1", "normal", 1, RunMode.NETWORK, "2026-11-18T00:00:00", None, "abc")


def test_corrida_con_manifiesto_y_verificacion_de_hashes(tmp_path):
    frame = pd.DataFrame({"t": [0.1, 0.2], "x": [1.0, 2.0]})
    path = write_run(tmp_path / "run", {"samples": frame}, _manifest())
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "network" and "samples.parquet" in manifest["files_sha256"]
    tables, loaded = read_run(tmp_path / "run")
    assert loaded.seed == 1 and tables["samples"].equals(frame)

    (tmp_path / "run" / "samples.parquet").write_bytes(b"alterado")
    with pytest.raises(ValueError, match="alterado"):
        verify_run(tmp_path / "run")


def test_manifiesto_incluye_todos_los_archivos_de_la_corrida(tmp_path):
    (tmp_path / "config.yaml").write_text("a: 1\n", encoding="utf-8")
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    finalize_run(tmp_path, _manifest())
    loaded = verify_run(tmp_path)
    assert set(loaded.files_sha256) == {"config.yaml", "summary.json"}
    assert loaded.files_sha256["config.yaml"] == sha256_file(tmp_path / "config.yaml")
    assert new_run_id("normal").endswith("_normal")


def test_puerto_ocupado_se_detecta_antes_de_lanzar_la_corrida():
    import socket

    from fdisim.opcua.factory import free_port
    from fdisim.orchestration.runtime import PortInUseError, check_ports_free

    cfg = load_config().to_dict()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        cfg["opcua"]["gateway"]["port"] = busy.getsockname()[1]
        cfg["opcua"]["plant_server"]["port"] = free_port()
        with pytest.raises(PortInUseError, match="opcua.gateway.port"):
            check_ports_free(cfg)
