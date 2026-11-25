"""Gráfica de tendencias en tiempo real (ECharts) con bandas de ataque (RF-47, RF-49).

El eje horizontal es la hora (SourceTimestamp de cada muestra); cada serie muestra los últimos
minutos del búfer circular de ``UiState``. ``chart_options`` es una función pura. Con
``show_attack_bands`` se sombrean los ataques que informa el orquestador (verdad de terreno,
solo en modo experimento); su tiempo simulado se convierte a hora con el último SIM.TIME
recibido y la escala de tiempo de la corrida (``attack_bands_epoch``).

Implementado en la Fase 3 (HMI v0); bandas de ataque en la Fase 7.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fdisim.ui.state import UiState

COLORS = ("#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c")


def chart_options(title: str, tags: list[str], y_name: str) -> dict[str, Any]:
    return {
        "title": {
            "text": f"{title} [{y_name}]" if y_name else title,
            "left": "left",
            "textStyle": {"fontSize": 14},
        },
        "tooltip": {"trigger": "axis"},
        "legend": {"data": tags, "top": 0, "right": 0},
        "grid": {"left": 50, "right": 20, "top": 40, "bottom": 30},
        "animation": False,
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value", "scale": True},
        "series": [
            {
                "name": tag,
                "type": "line",
                "showSymbol": False,
                "step": "end" if tag.endswith(".SP") else False,
                "lineStyle": {"type": "dashed" if tag.endswith(".SP") else "solid"},
                "color": COLORS[i % len(COLORS)],
                "data": [],
            }
            for i, tag in enumerate(tags)
        ],
    }


def series_data(state: UiState, tag: str) -> list[list[float]]:
    return [[1000.0 * t, v] for t, v in state.trends.get(tag, ())]


def attack_bands_epoch(state: UiState) -> list[list[dict[str, float]]]:
    """Ventanas de ataque en milisegundos de época, para el eje de hora de las tendencias."""
    clock = state.latest.get("SIM.TIME")
    if clock is None or not state.attack_events:
        return []
    scale = float(state.run_status.get("time_scale") or 1.0)

    def epoch_ms(t_sim: float) -> float:
        return 1000.0 * (clock.source_ts + (t_sim - clock.value) / scale)

    bands = []
    for event in state.attack_events:
        end = event.get("t_end")
        bands.append(
            [
                {"xAxis": epoch_ms(float(event["t_start"]))},
                {"xAxis": epoch_ms(float(end) if end is not None else clock.value)},
            ]
        )
    return bands


def trend_chart(
    state: UiState,
    tags: list[str],
    title: str,
    show_attack_bands: bool = False,
    y_name: str = "",
) -> Callable[[], None]:
    """Crea la gráfica en la página actual y devuelve su función de refresco."""
    from nicegui import ui

    options = chart_options(title, tags, y_name)
    if show_attack_bands:
        options["series"][0]["markArea"] = {
            "silent": True,
            "itemStyle": {"color": "rgba(239,68,68,0.15)"},
            "data": [],
        }
    chart = ui.echart(options).classes("w-full h-64")

    def refresh() -> None:
        for i, tag in enumerate(tags):
            chart.options["series"][i]["data"] = series_data(state, tag)
        if show_attack_bands:
            chart.options["series"][0]["markArea"]["data"] = attack_bands_epoch(state)
        chart.update()

    return refresh
