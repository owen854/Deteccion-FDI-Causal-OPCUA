"""Indicadores de una corrida en red (Fase 3) y componentes puros de la HMI v0 (RF-47)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from fdisim.common.types import Sample
from fdisim.opcua.security import PasswordUserManager
from fdisim.orchestration.run_summary import (
    data_quality,
    disturbance_windows,
    setpoint_tracking,
)
from fdisim.ui.components.tank_synoptic import render_svg
from fdisim.ui.components.trend_chart import chart_options, series_data
from fdisim.ui.state import UiState

TAGS = ("LT-101", "LT-102", "FT-101")


def _frames(n: int = 50, drop: int | None = None, corrupt: int | None = None):
    ts = 1000.0 + 0.1 * np.arange(1, n + 1)
    gt = pd.DataFrame({"sim_time": 0.1 * np.arange(1, n + 1), "source_ts": ts})
    rows = []
    for tag in TAGS:
        values = np.linspace(10, 11, n)
        gt[f"meas_{tag}"] = values
        for i, (t, v) in enumerate(zip(ts, values, strict=True)):
            if i == drop:
                continue
            value = v + (0.5 if i == corrupt and tag == "LT-102" else 0.0)
            rows.append(
                {
                    "tag": tag,
                    "value": value,
                    "source_ts": t,
                    "server_ts": t + 0.04,
                    "received_ts": t + 0.09,
                    "status": "Good",
                }
            )
    rows.append(
        {
            "tag": "P-101",
            "value": 59.0,
            "source_ts": 999.0,
            "server_ts": 999.0,
            "received_ts": 999.1,
            "status": "Good",
        }
    )
    return pd.DataFrame(rows), gt


def test_completitud_transparencia_y_latencias():
    samples, gt = _frames()
    q = data_quality(samples, gt)
    assert all(v["pct"] == 100.0 for v in q["completeness"].values())
    assert all(v["mismatches"] == 0 for v in q["transparency"].values())
    assert math.isclose(q["latency_ms"]["end_to_end"]["p50"], 90.0, abs_tol=0.01)
    assert math.isclose(q["latency_ms"]["plant_to_gateway"]["p95"], 40.0, abs_tol=0.01)
    assert q["event_samples"]["P-101"] == 1


def test_detecta_muestras_perdidas_y_valores_alterados():
    samples, gt = _frames(drop=10, corrupt=20)
    q = data_quality(samples, gt)
    assert q["completeness"]["LT-101"]["received"] == 49
    assert q["transparency"]["LT-102"]["mismatches"] == 1
    assert math.isclose(q["transparency"]["LT-102"]["max_abs_diff"], 0.5, abs_tol=1e-9)


def test_union_tolera_el_redondeo_de_1_us_de_las_marcas_opc_ua():
    samples, gt = _frames()
    jitter = np.where(np.arange(len(samples)) % 3 == 0, 1e-6, 0.0)  # como DateTime de OPC UA
    samples["source_ts"] = samples["source_ts"] + jitter
    q = data_quality(samples, gt)
    assert all(v["pct"] == 100.0 for v in q["completeness"].values())
    assert all(v["mismatches"] == 0 for v in q["transparency"].values())


def test_seguimiento_de_consigna_por_tramos():
    t = np.arange(0.1, 1300.0, 0.1)
    sp = np.where(t < 600, 25.0, 30.0)
    y = np.where(t < 600, 25.0, 30.0 - 5.0 * np.exp(-(t - 600) / 60.0))
    segments = setpoint_tracking(t, y, sp)
    assert [s["setpoint"] for s in segments] == [25.0, 30.0]
    assert all(s["error_pct"] < 0.1 and not s["perturbado"] for s in segments)
    short = setpoint_tracking(t[:7000], y[:7000], sp[:7000])  # el segundo tramo dura 100 s
    assert len(short) == 1


def test_tramos_con_perturbacion_legitima_se_marcan():
    disturbances = [
        {"type": "outlet_area", "t_s": 900, "duration_s": 120},
        {"type": "process_noise", "t_s": 0, "duration_s": 1800},  # el ruido no cuenta
    ]
    windows = disturbance_windows(disturbances)
    assert windows == [(900.0, 1520.0)]
    t = np.arange(0.1, 1300.0, 0.1)
    sp = np.where(t < 600, 25.0, 30.0)
    segments = setpoint_tracking(t, np.full_like(t, 25.0), sp, disturbed=windows)
    assert [s["perturbado"] for s in segments] == [False, True]


def test_gestor_de_usuarios_limita_por_servidor():
    creds = {"gateway": "a", "monitor": "b"}
    manager = PasswordUserManager(creds, allowed=("gateway",))
    assert manager.get_user(None, "gateway", "a") is not None
    assert manager.get_user(None, "monitor", "b") is None  # existe, pero no se admite aquí


def test_sinoptico_muestra_valores_y_consigna():
    svg = render_svg(
        {"LT-101": 16.0, "LT-102": 25.0, "FT-101": 88.4, "P-101": 59.0, "LIC-102.SP": 30.0}
    )
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "LT-101 16.00 cm" in svg and "SP 30.0 cm" in svg and "P-101 59.0 %" in svg
    empty = render_svg({})
    assert "LT-102 —" in empty and "SP " not in empty


def test_estado_de_la_hmi_submuestrea_tendencias():
    state = UiState(max_points=3, trend_step_s=0.5)
    for i in range(10):
        state.push_sample(Sample("LT-102", 20.0 + i, 100.0 + 0.1 * i, 0, 0))
    buf = state.trends["LT-102"]
    assert len(buf) == 2 and buf[-1][0] - buf[0][0] >= 0.5
    assert state.value("LT-102") == 29.0 and math.isnan(state.value("LT-101"))
    assert series_data(state, "LT-102")[0][0] == 100000.0


def test_consigna_se_dibuja_continua_en_la_tendencia():
    state = UiState(trend_step_s=0.5)
    state.push_sample(Sample("LIC-102.SP", 25.0, 100.0, 0, 0))
    for i in range(1, 11):
        state.push_sample(Sample("SIM.TIME", 0.1 * i, 100.0 + 0.1 * i, 0, 0))
    assert [v for _, v in state.trends["LIC-102.SP"]] == [25.0, 25.0, 25.0]


def test_opciones_de_tendencia():
    options = chart_options("Niveles", ["LT-102", "LIC-102.SP"], "cm")
    assert options["title"]["text"] == "Niveles [cm]"
    assert options["series"][1]["step"] == "end"
    assert options["xAxis"]["type"] == "time"
