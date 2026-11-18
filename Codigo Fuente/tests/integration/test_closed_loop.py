"""Integración: lazo cerrado planta → gateway → controlador y gateway transparente (RF-08, RF-13).

Requiere asyncua; se omite si no está instalado.
"""

from __future__ import annotations

import pytest

from conftest import pending

pytestmark = pytest.mark.integration


@pending("Fases 3–4", "RF-08/RF-13/RF-22")
def test_lazo_cerrado_regula_la_consigna_en_modo_red():
    pytest.importorskip("asyncua")
    from fdisim.common.paths import SCENARIOS_DIR
    from fdisim.orchestration.runtime import run_scenario_network

    run_dir = run_scenario_network(SCENARIOS_DIR / "normal.yaml", seed=1)
    assert (run_dir / "manifest.json").is_file()
