"""Integración de extremo a extremo: ``fdisim run`` en modo en red con procesos reales.

Lanza planta, gateway, controlador y monitor como procesos independientes (RF-54) con una PKI
temporal y puertos libres, corre un escenario corto y verifica la corrida guardada: manifiesto
con hashes válidos (RF-26), bitácoras por componente (RF-55) y criterios de la Fase 3.
Requiere asyncua; se omite si no está instalado.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("asyncua")

from fdisim.common.paths import SCENARIOS_DIR  # noqa: E402
from fdisim.data.storage import verify_run  # noqa: E402
from fdisim.opcua.factory import free_port  # noqa: E402
from fdisim.opcua.security import setup_pki  # noqa: E402
from fdisim.orchestration.runtime import run_scenario_network  # noqa: E402

pytestmark = pytest.mark.integration


def test_lazo_cerrado_regula_la_consigna_en_modo_red(tmp_path):
    certs = tmp_path / "certs"
    setup_pki(certs)
    overrides = {
        "opcua": {
            "plant_server": {"port": free_port()},
            "gateway": {"port": free_port()},
            "security": {"certs_dir": str(certs)},
        },
        "data": {"raw_dir": str(tmp_path / "raw")},
        "logging": {"dir": str(tmp_path / "logs")},
    }
    run_dir = run_scenario_network(
        SCENARIOS_DIR / "normal.yaml", seed=1, duration_s=20.0, time_scale=2.0, overrides=overrides
    )
    assert (run_dir / "manifest.json").is_file()
    manifest = verify_run(run_dir)
    assert {"samples.parquet", "ground_truth.parquet", "config.yaml", "summary.json"} <= set(
        manifest.files_sha256
    )
    assert manifest.mode.value == "network" and manifest.seed == 1

    logs = tmp_path / "logs" / run_dir.name
    expected = {"orchestrator", "plant_server", "gateway", "controller", "monitor"}
    assert {p.stem for p in logs.glob("*.log")} == expected

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    failed = [name for name, ok in summary["criteria"].items() if ok is False]
    assert not failed, failed
