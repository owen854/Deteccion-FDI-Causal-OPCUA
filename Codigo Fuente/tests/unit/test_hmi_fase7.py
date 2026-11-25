"""HMI de la Fase 7: alarmas, grafo, detección, comunicaciones y gestor de corridas (RF-47 a RF-52).

Se prueban las funciones puras de cada página y el estado compartido; la interfaz NiceGUI se
verificó de punta a punta en el navegador (docs/evidencias/fase7).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fdisim.common.types import LT_101, LT_102, Sample
from fdisim.ui.components.alarm_table import alarm_rows
from fdisim.ui.components.causal_graph_view import COLORS, graph_options
from fdisim.ui.components.header import NAVIGATION, alarm_banner
from fdisim.ui.components.trend_chart import attack_bands_epoch
from fdisim.ui.pages.causal_model import alarm_status
from fdisim.ui.pages.communication import latency_summary
from fdisim.ui.pages.detection import attack_bands, scaled
from fdisim.ui.run_manager import RunManager, scenario_catalog
from fdisim.ui.state import UiState


def _detection(t: float, alarm: bool, suspected: str | None = None, alarms=()):
    return {
        "t": t,
        "detector": "causal",
        "alarm": alarm,
        "suspected": suspected,
        "triggered": ["LT-102:20"] if alarm else [],
        "scores": {"LT-102:20": 5.0 if alarm else 0.1, "max": 2.0 if alarm else 0.1},
        "alarms": list(alarms),
    }


def test_navegacion_con_todas_las_paginas():
    assert [target for target, _ in NAVIGATION] == [
        "/",
        "/experimentos",
        "/deteccion",
        "/grafo",
        "/resultados",
        "/comunicacion",
    ]


def test_estado_recibe_detecciones_y_alarmas():
    state = UiState()
    assert alarm_banner(state)[0] == "Detección inactiva"
    state.push_detection(_detection(10.0, False))
    assert alarm_banner(state) == ("✓ Sin alarmas", "bg-green-700")
    alarm = {
        "alarm_id": "C001",
        "detector": "causal",
        "kind": "residual",
        "t": 10.5,
        "t_end": None,
        "variables": [LT_102],
        "score": 3.2,
        "suspected_tag": LT_102,
        "state": "active",
    }
    state.push_detection(_detection(10.5, True, LT_102, [alarm]))
    text, color = alarm_banner(state)
    assert "ALARMA causal" in text and LT_102 in text and color == "bg-red-600"
    assert state.det_scores["causal"]["LT-102:20"][-1] == (10.5, 5.0)
    assert alarm_status(state) == ({LT_102}, LT_102)
    rows = alarm_rows(state)
    assert rows[0]["id"] == "C001" and rows[0]["estado"] == "activa"
    state.acknowledged.add("C001")
    assert alarm_rows(state)[0]["estado"] == "reconocida"
    state.push_detection(
        _detection(13.0, False, None, [{**alarm, "t_end": 13.0, "state": "closed"}])
    )
    assert alarm_rows(state)[0]["estado"] == "cerrada"
    assert alarm_status(state) == (set(), None)


def test_grafo_resalta_la_variable_sospechosa():
    links = [
        {"source": LT_101, "target": LT_102, "lag": 1},
        {"source": LT_102, "target": LT_102, "lag": 1},  # autodependencia: no se dibuja
    ]
    options = graph_options(links, alarmed={LT_102}, suspected=LT_102)
    nodes = {n["name"]: n for n in options["series"][0]["data"]}
    assert nodes[LT_102]["itemStyle"]["color"] == COLORS["suspected"]
    assert nodes[LT_101]["itemStyle"]["color"] == COLORS["normal"]
    edges = options["series"][0]["links"]
    assert len(edges) == 1 and edges[0]["lineStyle"]["color"] == COLORS["alarm"]


def test_residuo_escalado_y_bandas_de_ataque():
    limits = {"upper": 2.0, "lower": -4.0}
    assert scaled(3.0, limits) == 1.5
    assert scaled(-2.0, limits) == -0.5
    state = UiState()
    state.attack_events = [{"t_start": 100.0, "t_end": None}, {"t_start": 10.0, "t_end": 20.0}]
    assert attack_bands(state, 150.0) == [
        [{"xAxis": 100.0}, {"xAxis": 150.0}],
        [{"xAxis": 10.0}, {"xAxis": 20.0}],
    ]
    clock = Sample("SIM.TIME", 100.0, source_ts=1000.0, server_ts=1000.0, received_ts=1000.1)
    state.latest["SIM.TIME"] = clock
    state.run_status = {"time_scale": 5.0}
    bands = attack_bands_epoch(state)
    assert bands[1][0]["xAxis"] == 1000.0 * (1000.0 + (10.0 - 100.0) / 5.0)


def test_latencias_de_la_hmi():
    assert latency_summary([]) is None
    summary = latency_summary([100.0, 200.0, 300.0, float("nan")])
    assert summary["n"] == 3 and summary["max"] == 300.0 and summary["p50"] == 200.0


def test_carga_resultados_de_una_corrida_guardada(tmp_path):
    folder = tmp_path / "corrida" / "detection"
    folder.mkdir(parents=True)
    for kind in ("causal", "threshold"):
        pd.DataFrame(
            {
                "run_id": ["r"] * 3,
                "sim_time": [0.0, 0.5, 1.0],
                "alarm": [0, 1, 1],
                "suspected": ["", LT_102, LT_102],
                "triggered": ["", "", ""],
                "processing_ms": [0.1] * 3,
                "LT-102:20": [0.1, 4.0, 5.0],
                "max": [0.1, 2.0, 2.5],
            }
        ).to_parquet(folder / f"{kind}.parquet")
    pd.DataFrame(
        [
            {
                "run_id": "r",
                "alarm_id": "C001",
                "detector": "causal",
                "kind": "residual",
                "t": 0.5,
                "t_end": float("nan"),
                "variables": LT_102,
                "score": 2.0,
                "suspected_tag": LT_102,
                "state": "active",
            }
        ]
    ).to_csv(folder / "alarms.csv", index=False)
    pd.DataFrame(
        [
            {
                "attack_id": "A1",
                "type": "bias",
                "targets": LT_102,
                "t_start": 0.5,
                "t_end": 1.0,
                "params": "{}",
            }
        ]
    ).to_parquet(tmp_path / "corrida" / "attacks.parquet")
    state = UiState()
    assert state.load_run_results(tmp_path / "corrida")
    assert state.detection_source == "corrida guardada corrida"
    assert len(state.det_scores["causal"]["LT-102:20"]) == 3
    assert state.active_alarm("causal")["suspected"] == LT_102
    assert state.attack_events[0]["targets"] == [LT_102]
    assert alarm_rows(state)[0]["variables"] == LT_102
    assert not UiState().load_run_results(tmp_path / "no_existe")


def test_gestor_de_corridas_y_catalogo(monkeypatch):
    from fdisim.common.config import load_config
    from fdisim.common.experiment_channel import ENV_ADDRESS, ENV_KEY

    monkeypatch.delenv(ENV_ADDRESS, raising=False)
    monkeypatch.delenv(ENV_KEY, raising=False)
    catalog = {item["name"]: item for item in scenario_catalog()}
    assert {"normal", "sesgo_lt102", "replay_lt102"} <= set(catalog)
    assert catalog["sesgo_lt102"]["attacks"] == 1
    state = UiState()
    manager = RunManager(load_config().to_dict(), state)
    assert manager.owns_runs and not manager.running
    manager._say("[fdisim] Corrida guardada en C:\\datos\\raw\\20261124_x (completed)")  # noqa: SLF001
    assert state.last_run_dir == "C:\\datos\\raw\\20261124_x"
    manager._say("[fdisim] Corrida offline guardada en /tmp/raw/y")  # noqa: SLF001
    assert state.last_run_dir == str(Path("/tmp/raw/y"))
    assert manager.stop() == "No hay una corrida en curso"
    manager.preparing = True  # mientras prepara el modelo no lanza corridas
    assert manager.start("x.yaml", "network").startswith("Espere")
