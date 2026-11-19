"""Integración de extremo a extremo: ``fdisim run`` en modo en red con procesos reales.

Lanza planta, gateway, controlador y monitor como procesos independientes (RF-54) con una PKI
temporal y puertos libres, corre un escenario corto con un ataque de sesgo y verifica la corrida
guardada: manifiesto con hashes válidos (RF-26), bitácoras por componente (RF-55), etiquetas
(RF-21) y los criterios de las Fases 3 y 4.
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


ATTACK_SCENARIO = """name: sesgo_red_corto
base: {base}
seed: 4
attacks:
  - id: A1
    type: bias
    targets: [LT-102]
    start_s: 8
    duration_s: 16
    params: {{ bias: 2.0 }}
    stealth: {{ enabled: true, envelope: [2.0, 45.0], max_rate_per_s: 0.5 }}
"""


def test_lazo_cerrado_regula_la_consigna_en_modo_red(tmp_path):
    """Fase 3 y Fase 4: corrida con procesos reales y un ataque de sesgo en el gateway."""
    certs = tmp_path / "certs"
    setup_pki(certs)
    scenario = tmp_path / "sesgo_red_corto.yaml"
    scenario.write_text(
        ATTACK_SCENARIO.format(base=(SCENARIOS_DIR / "normal.yaml").as_posix()), encoding="utf-8"
    )
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
        scenario, seed=1, duration_s=30.0, time_scale=2.0, overrides=overrides
    )
    assert (run_dir / "manifest.json").is_file()
    manifest = verify_run(run_dir)
    assert {
        "samples.parquet",
        "ground_truth.parquet",
        "attacks.parquet",
        "config.yaml",
        "scenario.yaml",
        "summary.json",
    } <= set(manifest.files_sha256)
    assert manifest.mode.value == "network" and manifest.seed == 1

    import pandas as pd

    samples = pd.read_parquet(run_dir / "samples.parquet")
    attacked = samples[(samples["tag"] == "LT-102") & (samples["label"] == 1)]["sim_time"]
    assert attacked.min() >= 8.0 and attacked.max() < 24.0  # RF-21: etiquetas en la ventana

    logs = tmp_path / "logs" / run_dir.name
    expected = {"orchestrator", "plant_server", "gateway", "controller", "monitor"}
    assert {p.stem for p in logs.glob("*.log")} == expected

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    failed = [name for name, ok in summary["criteria"].items() if ok is False]
    assert not failed, failed
    assert summary["criteria"]["RF-17 sesgo recibido = b"] is True
