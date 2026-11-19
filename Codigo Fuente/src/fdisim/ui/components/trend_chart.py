"""Gráfica de tendencias en tiempo real (ECharts) con bandas de ataque (RF-47, RF-49).

El eje horizontal es la hora (SourceTimestamp de cada muestra); cada serie muestra los últimos
minutos del búfer circular de ``UiState``. ``chart_options`` es una función pura; las bandas de
ataque (``show_attack_bands``) se agregan en la Fase 7, cuando la HMI reciba las etiquetas.

Implementado en la Fase 3 (HMI v0).
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


def trend_chart(
    state: UiState,
    tags: list[str],
    title: str,
    show_attack_bands: bool = False,
    y_name: str = "",
) -> Callable[[], None]:
    """Crea la gráfica en la página actual y devuelve su función de refresco."""
    from nicegui import ui

    if show_attack_bands:
        raise NotImplementedError("Fase 7 — RF-49: bandas de ataque")
    chart = ui.echart(chart_options(title, tags, y_name)).classes("w-full h-64")

    def refresh() -> None:
        for i, tag in enumerate(tags):
            chart.options["series"][i]["data"] = series_data(state, tag)
        chart.update()

    return refresh
