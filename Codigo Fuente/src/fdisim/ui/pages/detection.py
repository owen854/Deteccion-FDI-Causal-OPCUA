"""Página «Detección» (``/deteccion``): residuos normalizados con sus umbrales, acumuladores y
alarmas del detector causal frente al método base, con las bandas de ataque (RF-49).

- **En vivo:** durante una corrida en red, las salidas de los detectores del monitor en línea
  llegan cada 0,5 s simulados por el canal de experimento (``RunManager.poll``).
- **Corrida guardada:** sin corrida en curso, muestra la última corrida con detecciones (en
  red u offline) o la que se elija en la lista.

Cada residuo se dibuja dividido por su límite calibrado (positivo o negativo), de modo que el
umbral es ±1 para todos. Las bandas rojas son la verdad de terreno de los ataques (solo en
modo experimento).

Implementado en la Fase 7.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from typing import Any

from fdisim.common import paths
from fdisim.ui.state import UiState

COLORS = ("#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#65a30d")


def load_limits(config: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    from fdisim.detection.pipeline import DETECTOR_FILE, model_dir_of

    path = model_dir_of(config) / DETECTOR_FILE
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["causal"]["limits"]


def scaled(value: float, limits: Mapping[str, float]) -> float:
    """Residuo dividido por su límite del lado correspondiente (umbral = ±1)."""
    if value >= 0:
        return value / limits["upper"] if limits.get("upper", 0) > 0 else value
    return -value / limits["lower"] if limits.get("lower", 0) < 0 else value


def attack_bands(state: UiState, t_max: float) -> list[list[dict[str, float]]]:
    bands = []
    for event in state.attack_events:
        start = float(event["t_start"])
        end = event.get("t_end")
        bands.append([{"xAxis": start}, {"xAxis": float(end) if end is not None else t_max}])
    return bands


def chart_options(title: str, names: list[str], y_name: str, unit_band: bool) -> dict[str, Any]:
    series = [
        {
            "name": name,
            "type": "line",
            "showSymbol": False,
            "sampling": "lttb",
            "color": COLORS[i % len(COLORS)],
            "data": [],
        }
        for i, name in enumerate(names)
    ]
    if series:
        series[0]["markArea"] = {
            "silent": True,
            "itemStyle": {"color": "rgba(239,68,68,0.15)"},
            "data": [],
        }
        if unit_band:
            series[0]["markLine"] = {
                "silent": True,
                "symbol": "none",
                "lineStyle": {"color": "#ef4444", "type": "dashed"},
                "data": [{"yAxis": 1}, {"yAxis": -1}],
            }
    return {
        "title": {"text": title, "textStyle": {"fontSize": 13}},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": names, "top": 0, "right": 0, "type": "scroll", "width": "65%"},
        "grid": {"left": 50, "right": 20, "top": 40, "bottom": 30},
        "animation": False,
        "xAxis": {"type": "value", "name": "t [s]", "scale": True},
        "yAxis": {"type": "value", "name": y_name, "scale": True},
        "series": series,
    }


def register(state: UiState, link: Any, manager: Any, config: Mapping[str, Any]) -> None:
    from nicegui import ui

    from fdisim.ui.components.alarm_table import alarm_table
    from fdisim.ui.components.header import page_header

    refresh_hz = float(config.get("ui", {}).get("refresh_hz", 4))

    @ui.page("/deteccion")
    def page() -> None:
        ui.page_title("FDISim-OPCUA · Detección")
        ui.query("body").style("background-color: #f1f5f9")
        refresh_header = page_header("Detección", state, link)
        limits = load_limits(config)
        one_step = [n for n in limits if n.endswith(":1")]
        horizon = [n for n in limits if not n.endswith(":1")]

        if not state.det_latest and not manager.running:
            _load_latest(state)

        with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
            with ui.card().classes("w-1/3"):
                ui.label("Detector causal").classes("font-bold")
                causal_label = ui.label().classes("text-lg")
                causal_detail = ui.label().classes("text-sm text-gray-600")
            with ui.card().classes("w-1/3"):
                ui.label("Método base (umbrales)").classes("font-bold")
                base_label = ui.label().classes("text-lg")
                base_detail = ui.label().classes("text-sm text-gray-600")
            with ui.card().classes("w-1/3"):
                ui.label("Fuente de los datos").classes("font-bold")
                source = ui.label().classes("text-sm")
                runs = _runs_with_detection()
                chooser = ui.select(
                    {str(p): p.name for p in runs},
                    label="Ver una corrida guardada",
                    with_input=True,
                ).classes("w-full")

                def load_selected() -> None:
                    if chooser.value and state.load_run_results(chooser.value):
                        ui.notify(f"Corrida {chooser.value} cargada")
                        refresh_charts()

                ui.button("Cargar", on_click=load_selected).props("outline")

        if not limits:
            with ui.card().classes("w-full"):
                ui.label(
                    "Los detectores no están calibrados: genere el modelo con «fdisim dataset» y "
                    "«fdisim train» (o espere a que la HMI termine la preparación)."
                )

        with ui.card().classes("w-full"):
            chart_h = ui.echart(
                chart_options("Residuos del gemelo causal / límite", horizon, "z / límite", True)
            ).classes("w-full h-64")
        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.card().classes("w-1/2"):
                chart_1 = ui.echart(
                    chart_options("Residuos a un paso / límite", one_step, "z / límite", True)
                ).classes("w-full h-60")
            with ui.card().classes("w-1/2"):
                chart_acc = ui.echart(
                    chart_options("Acumuladores CUSUM / límite h", one_step, "S / h", True)
                ).classes("w-full h-60")
        with ui.card().classes("w-full"):
            chart_alarm = ui.echart(
                chart_options("Alarmas: causal frente a base", ["Causal", "Base"], "alarma", False)
            ).classes("w-full h-44")
        with ui.card().classes("w-full"):
            ui.label("Alarmas (RF-36)").classes("font-bold")
            refresh_table = alarm_table(state, manager.acknowledge)

        def series_of(kind: str, name: str, transform: Any = None) -> list[list[float]]:
            data = state.det_scores.get(kind, {}).get(name, ())
            if transform is None:
                return [[t, v] for t, v in data]
            return [[t, transform(v)] for t, v in data]

        def refresh_charts() -> None:
            t_max = max((buf[-1][0] for buf in state.det_alarm.values() if buf), default=0.0)
            bands = attack_bands(state, t_max)
            for chart, names, prefix in (
                (chart_h, horizon, ""),
                (chart_1, one_step, ""),
            ):
                for i, name in enumerate(names):
                    lim = limits.get(name, {})
                    chart.options["series"][i]["data"] = series_of(
                        "causal", prefix + name, lambda v, lim=lim: scaled(v, lim)
                    )
                if names:
                    chart.options["series"][0]["markArea"]["data"] = bands
                chart.update()
            for i, name in enumerate(one_step):
                h = limits.get(name, {}).get("cusum", 0.0)
                chart_acc.options["series"][i]["data"] = series_of(
                    "causal", f"cusum:{name}", lambda v, h=h: v / h if h > 0 else v
                )
            if one_step:
                chart_acc.options["series"][0]["markArea"]["data"] = bands
            chart_acc.update()
            for i, kind in enumerate(("causal", "threshold")):
                offset = 1.1 if kind == "causal" else 0.0
                chart_alarm.options["series"][i]["step"] = "end"
                chart_alarm.options["series"][i]["data"] = [
                    [t, v + offset] for t, v in state.det_alarm.get(kind, ())
                ]
            chart_alarm.options["series"][0]["markArea"]["data"] = bands
            chart_alarm.update()
            refresh_table()

        def refresh_fast() -> None:
            refresh_header()
            for kind, label, detail in (
                ("causal", causal_label, causal_detail),
                ("threshold", base_label, base_detail),
            ):
                latest = state.det_latest.get(kind)
                if latest is None:
                    label.text, detail.text = "Sin datos", ""
                    label.classes(replace="text-lg text-gray-500")
                    continue
                if latest.get("alarm"):
                    label.text = f"EN ALARMA · sospechosa {latest.get('suspected') or '—'}"
                    label.classes(replace="text-lg font-bold text-red-600")
                else:
                    label.text = "Normal"
                    label.classes(replace="text-lg font-bold text-green-700")
                triggered = latest.get("triggered") or []
                detail.text = f"t = {float(latest['t']):.1f} s" + (
                    f" · en alarma: {', '.join(triggered)}" if triggered else ""
                )
            source.text = f"Mostrando: {state.detection_source}"

        ui.timer(1.0 / refresh_hz, refresh_fast)
        ui.timer(1.0, refresh_charts)


def _runs_with_detection() -> list[Any]:
    raw = paths.RAW_DIR
    if not raw.is_dir():
        return []
    runs = [p for p in raw.iterdir() if (p / "detection" / "causal.parquet").is_file()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)[:50]


def _load_latest(state: UiState) -> None:
    runs = _runs_with_detection()
    target = state.last_run_dir or (str(runs[0]) if runs else None)
    if target:
        with contextlib.suppress(Exception):  # una corrida incompleta no debe romper la página
            state.load_run_results(target)
