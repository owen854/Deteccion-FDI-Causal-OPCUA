"""Página «Grafo causal» (``/grafo``): grafo de referencia con las inconsistencias resaltadas y
comparación del grafo físico con los aprendidos (RF-50).

- El grafo de referencia es el del modelo causal en uso (``graph.json``). Durante una alarma
  del detector causal, el nodo de la variable sospechosa se pinta de rojo y los nodos con
  residuos en alarma, de ámbar (RF-37).
- La tabla compara el grafo físico con los que descubrieron PCMCI+ y Granger (SHD, precisión y
  exhaustividad), tomada del reporte de entrenamiento (``report.json``).

Implementado en la Fase 7.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fdisim.ui.state import UiState


def alarm_status(state: UiState) -> tuple[set[str], str | None]:
    """Variables con residuos en alarma y variable sospechosa del detector causal."""
    latest = state.det_latest.get("causal")
    if not latest or not latest.get("alarm"):
        return set(), None
    alarmed = {name.rsplit(":", 1)[0] for name in latest.get("triggered") or []}
    return alarmed, latest.get("suspected")


def register(state: UiState, link: Any, config: Mapping[str, Any]) -> None:
    from nicegui import ui

    from fdisim.detection.pipeline import model_dir_of
    from fdisim.ui.components.causal_graph_view import causal_graph_view
    from fdisim.ui.components.header import page_header

    @ui.page("/grafo")
    def page() -> None:
        ui.page_title("FDISim-OPCUA · Grafo causal")
        ui.query("body").style("background-color: #f1f5f9")
        refresh_header = page_header("Grafo causal", state, link)
        model_dir = model_dir_of(config)
        graph_path = model_dir / "graph.json"
        if not graph_path.is_file():
            with ui.card().classes("w-full"):
                ui.label(f"No hay un modelo causal en {model_dir}.")
            ui.timer(1.0, refresh_header)
            return
        graph = json.loads(graph_path.read_text(encoding="utf-8"))

        with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
            with ui.card().classes("w-3/5"):
                ui.label("Grafo de referencia del proceso").classes("font-bold")
                ui.label(
                    "Verde: consistente · ámbar: residuo en alarma · rojo: variable sospechosa"
                ).classes("text-sm text-gray-600")
                ui.label(
                    "LIC-102.SP consigna · P-101 orden de la bomba · FT-101 caudal de entrada · "
                    "LT-101 nivel del tanque 1 · LT-102 nivel del tanque 2"
                ).classes("text-xs text-gray-500")
                refresh_graph = causal_graph_view(graph["links"], lambda: alarm_status(state))
                status = ui.label().classes("text-sm")
            with ui.card().classes("w-2/5"):
                ui.label("Mecanismos (enlaces y retardos)").classes("font-bold")
                rows = [
                    {
                        "enlace": f"{lk['source']} → {lk['target']}",
                        "retardo": lk["lag"],
                        "mecanismo": lk.get("mechanism", ""),
                    }
                    for lk in graph["links"]
                ]
                ui.table(
                    rows=rows,
                    columns=[
                        {"name": k, "label": v, "field": k, "align": "left"}
                        for k, v in (
                            ("enlace", "Enlace"),
                            ("retardo", "τ"),
                            ("mecanismo", "Mecanismo"),
                        )
                    ],
                    pagination=8,
                ).classes("w-full text-xs")

        report_path = model_dir / "report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            with ui.card().classes("w-full"):
                ui.label("Grafo físico frente a los grafos aprendidos (RF-30)").classes("font-bold")
                rows = [
                    {
                        "metodo": name,
                        "enlaces": m["edges"],
                        "shd": m["shd"],
                        "precision": f"{m['precision_sin_retardo']:.2f}",
                        "exhaustividad": f"{m['recall_sin_retardo']:.2f}",
                    }
                    for name, m in report.get("metrics_vs_physical", {}).items()
                ]
                ui.table(
                    rows=rows,
                    columns=[
                        {"name": k, "label": v, "field": k, "align": "left"}
                        for k, v in (
                            ("metodo", "Método"),
                            ("enlaces", "Enlaces"),
                            ("shd", "SHD"),
                            ("precision", "Precisión (sin retardo)"),
                            ("exhaustividad", "Exhaustividad (sin retardo)"),
                        )
                    ],
                ).classes("w-full")
                ui.label(
                    "PCMCI+ es el más preciso; Granger sobre-conecta el lazo cerrado. Ningún "
                    "método recupera solo el grafo físico: los datos lo validan y lo afinan."
                ).classes("text-sm text-gray-600")

        def refresh() -> None:
            refresh_header()
            refresh_graph()
            alarmed, suspected = alarm_status(state)
            status.text = (
                f"Alarma causal: residuos en alarma en {', '.join(sorted(alarmed)) or '—'}; "
                f"variable sospechosa {suspected or '—'}"
                if suspected or alarmed
                else "Sin inconsistencias causales en este momento"
            )

        ui.timer(1.0, refresh)
