"""Visualización del grafo causal con resaltado de inconsistencias (RF-50).

Se dibuja con ECharts (serie ``graph``) con posiciones fijas que siguen el flujo del proceso:
consigna → bomba → caudal → tanque 1 → tanque 2 → controlador. Cada enlace del grafo de
referencia muestra sus retardos. Durante una alarma del detector causal:

- en rojo, el nodo de la variable sospechosa (identificación, RF-37);
- en ámbar, los nodos cuyos residuos están en alarma y los enlaces que los alimentan.

Implementado en la Fase 7.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102

POSITIONS: Mapping[str, tuple[float, float]] = {
    SP_102: (0, 100),
    P_101: (160, 0),
    FT_101: (340, 0),
    LT_101: (520, 0),
    LT_102: (520, 200),
}
DESCRIPTIONS = {
    SP_102: "Consigna",
    P_101: "Bomba (orden)",
    FT_101: "Caudal de entrada",
    LT_101: "Nivel tanque 1",
    LT_102: "Nivel tanque 2",
}
COLORS = {"normal": "#16a34a", "alarm": "#f59e0b", "suspected": "#dc2626"}


def graph_options(
    links: Iterable[Mapping[str, Any]],
    alarmed: set[str] | None = None,
    suspected: str | None = None,
) -> dict[str, Any]:
    """Opciones ECharts del grafo (función pura): nodos coloreados por estado."""
    alarmed = alarmed or set()
    lags: dict[tuple[str, str], list[int]] = {}
    for link in links:
        if link["source"] == link["target"]:
            continue  # autodependencias: se omiten para no recargar el dibujo
        lags.setdefault((link["source"], link["target"]), []).append(int(link["lag"]))

    def color(tag: str) -> str:
        if tag == suspected:
            return COLORS["suspected"]
        return COLORS["alarm"] if tag in alarmed else COLORS["normal"]

    nodes = [
        {
            "name": tag,
            "x": x,
            "y": y,
            "symbolSize": 72,
            "itemStyle": {"color": color(tag)},
            "label": {"show": True, "formatter": tag, "fontSize": 12, "fontWeight": "bold"},
            "tooltip": {"formatter": f"{tag}: {DESCRIPTIONS[tag]}"},
        }
        for tag, (x, y) in POSITIONS.items()
    ]
    edges = []
    for (source, target), values in lags.items():
        hot = target in alarmed or target == suspected
        edges.append(
            {
                "source": source,
                "target": target,
                "label": {"show": True, "formatter": "τ " + ",".join(map(str, sorted(values)))},
                "lineStyle": {
                    "width": 3 if hot else 1.5,
                    "color": COLORS["alarm"] if hot else "#64748b",
                    "curveness": 0.25 if (target, source) in lags else 0.0,
                },
            }
        )
    return {
        "animation": False,
        "tooltip": {},
        "series": [
            {
                "type": "graph",
                "layout": "none",
                "roam": False,
                "edgeSymbol": ["none", "arrow"],
                "edgeSymbolSize": 10,
                "data": nodes,
                "links": edges,
                "label": {"color": "#ffffff"},
                "edgeLabel": {"fontSize": 10},
            }
        ],
    }


def causal_graph_view(
    links: Iterable[Mapping[str, Any]],
    status: Callable[[], tuple[set[str], str | None]],
) -> Callable[[], None]:
    """Crea el grafo en la página actual; ``status`` da las variables en alarma y la sospechosa."""
    from nicegui import ui

    links = list(links)
    chart = ui.echart(graph_options(links)).classes("w-full h-96")

    def refresh() -> None:
        alarmed, suspected = status()
        chart.options.clear()
        chart.options.update(graph_options(links, alarmed, suspected))
        chart.update()

    return refresh
