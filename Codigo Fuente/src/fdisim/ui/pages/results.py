"""Página «Resultados» (``/resultados``): métricas comparativas causal vs. base, con exportación
(RF-51).

- **Evaluación sobre el dataset de prueba** (``fdisim detect --data``): indicadores globales y
  por escenario (DR, retardo, FPR, F1, AUC e identificación) y las figuras del reporte. Un botón
  la ejecuta de nuevo en segundo plano.
- **Corridas guardadas**: el resultado de los detectores en cada corrida (en red u offline).
- **Exportación**: descarga de ``summary.csv``, ``metrics_by_run.csv`` y ``report.md``.

Las campañas con repeticiones y pruebas estadísticas (RF-43, RF-45) son de la Fase 8.

Implementado en la Fase 7.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any

from fdisim.common import paths
from fdisim.ui.state import UiState

LABELS = {"causal": "Causal", "threshold": "Base"}


def _pct(value: Any) -> str:
    return (
        "—"
        if value is None or (isinstance(value, float) and math.isnan(value))
        else f"{100 * value:.1f} %"
    )


def _num(value: Any, digits: int = 1) -> str:
    return (
        "—"
        if value is None or (isinstance(value, float) and math.isnan(value))
        else f"{value:.{digits}f}"
    )


def evaluation_dirs() -> list[Path]:
    if not paths.RESULTS_DIR.is_dir():
        return []
    found = [p.parent for p in paths.RESULTS_DIR.glob("deteccion_*/summary.json")]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def run_rows() -> list[dict[str, Any]]:
    rows = []
    if not paths.RAW_DIR.is_dir():
        return rows
    runs = [p for p in paths.RAW_DIR.iterdir() if (p / "detection" / "summary.json").is_file()]
    for run in sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
        data = json.loads((run / "detection" / "summary.json").read_text(encoding="utf-8"))
        for m in data.get("metrics", []):
            attack = m.get("attack_id") or ""
            rows.append(
                {
                    "corrida": run.name,
                    "detector": LABELS.get(m["detector"], m["detector"]),
                    "ataque": f"{attack} ({m.get('targets')})" if attack else "sin ataque",
                    "detectado": ("sí" if m.get("detected") else "no") if attack else "—",
                    "retardo": _num(m.get("delay_s")),
                    "identificada": m.get("identified") or "—",
                    "fpr": _pct(m.get("fpr")),
                }
            )
    return rows


def register(state: UiState, link: Any, manager: Any) -> None:
    from nicegui import ui

    from fdisim.ui.components.header import page_header

    job: dict[str, Any] = {"running": False, "message": ""}

    def evaluate_dataset() -> None:
        try:
            manager._run_blocking(  # noqa: SLF001 (mismo paquete)
                ["detect", "--data", str(paths.PROCESSED_DIR / "v1" / "test.parquet")]
            )
            job["message"] = "Evaluación terminada: recargue la página"
        except Exception as exc:
            job["message"] = f"La evaluación falló: {exc}"
        finally:
            job["running"] = False

    @ui.page("/resultados")
    def page() -> None:
        ui.page_title("FDISim-OPCUA · Resultados")
        ui.query("body").style("background-color: #f1f5f9")
        refresh_header = page_header("Resultados", state, link)
        dirs = evaluation_dirs()

        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Evaluación de los detectores sobre el dataset de prueba").classes(
                    "font-bold"
                )
                status = ui.label().classes("text-sm text-gray-600")

                def start_evaluation() -> None:
                    if job["running"]:
                        return
                    job.update(running=True, message="Evaluando el dataset de prueba…")
                    threading.Thread(target=evaluate_dataset, daemon=True).start()

                ui.button("Evaluar de nuevo", on_click=start_evaluation).props("outline")
            if not dirs:
                ui.label(
                    "Aún no hay evaluaciones. Pulse «Evaluar de nuevo» o ejecute "
                    "«fdisim detect --data data/processed/v1/test.parquet»."
                )
            else:
                folder = dirs[0]
                report = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
                ui.label(f"{folder.name} · {report.get('created_at', '')}").classes(
                    "text-sm text-gray-600"
                )
                overall = report.get("overall", {})
                indicators = (
                    ("Ataques evaluados", "attacks", lambda v: _num(v, 0)),
                    ("Tasa de detección (DR)", "dr", _pct),
                    ("Retardo medio [s]", "delay_mean_s", _num),
                    ("FPR en corridas normales", "fpr_normal", _pct),
                    ("Falsas alarmas por hora", "false_alarms_per_h_normal", _num),
                    ("Identificación correcta", "identification", _pct),
                    ("Procesamiento p95 [ms]", "processing_p95_ms", lambda v: _num(v, 3)),
                )
                ui.table(
                    rows=[
                        {
                            "indicador": label,
                            "causal": fmt(overall.get("causal", {}).get(key)),
                            "base": fmt(overall.get("threshold", {}).get(key)),
                        }
                        for label, key, fmt in indicators
                    ],
                    columns=[
                        {
                            "name": "indicador",
                            "label": "Indicador",
                            "field": "indicador",
                            "align": "left",
                        },
                        {"name": "causal", "label": "Causal", "field": "causal"},
                        {"name": "base", "label": "Base (umbrales)", "field": "base"},
                    ],
                ).classes("w-full")
                ui.label("Por escenario").classes("font-bold mt-2")
                ui.table(
                    rows=[
                        {
                            "escenario": r["scenario"],
                            "detector": LABELS.get(r["detector"], r["detector"]),
                            "dr": _pct(r.get("dr")),
                            "retardo": _num(r.get("delay_mean_s")),
                            "fpr": _pct(r.get("fpr")),
                            "f1": _num(r.get("f1"), 3),
                            "auc": _num(r.get("auc"), 3),
                            "id": _pct(r.get("identification")),
                        }
                        for r in report.get("by_scenario", [])
                    ],
                    columns=[
                        {"name": k, "label": v, "field": k, "align": "left"}
                        for k, v in (
                            ("escenario", "Escenario"),
                            ("detector", "Detector"),
                            ("dr", "DR"),
                            ("retardo", "Retardo [s]"),
                            ("fpr", "FPR"),
                            ("f1", "F1"),
                            ("auc", "AUC"),
                            ("id", "Identificación"),
                        )
                    ],
                    pagination=18,
                ).classes("w-full")
                figure = folder / "figures" / "dr_retardo.png"
                if figure.is_file():
                    ui.image(str(figure)).classes("w-full")
                with ui.row().classes("gap-2"):
                    for name in ("summary.csv", "metrics_by_run.csv", "report.md"):
                        if (folder / name).is_file():
                            ui.button(
                                f"Descargar {name}",
                                on_click=lambda n=name, f=folder: ui.download(f / n),
                            ).props("outline")

        with ui.card().classes("w-full"):
            ui.label("Corridas guardadas con detección").classes("font-bold")
            ui.table(
                rows=run_rows(),
                columns=[
                    {"name": k, "label": v, "field": k, "align": "left"}
                    for k, v in (
                        ("corrida", "Corrida"),
                        ("detector", "Detector"),
                        ("ataque", "Ataque"),
                        ("detectado", "Detectado"),
                        ("retardo", "Retardo [s]"),
                        ("identificada", "Variable identificada"),
                        ("fpr", "FPR"),
                    )
                ],
                pagination=12,
            ).classes("w-full")

        def refresh() -> None:
            refresh_header()
            status.text = job["message"]

        ui.timer(1.0, refresh)
