"""Reporte de evaluación de los detectores sobre un dataset etiquetado (RF-41, RF-42, RF-44).

Escribe en la carpeta de salida ``report.md``, ``summary.json`` y las figuras (PNG a 300 dpi):

- ``figures/dr_retardo.png``: tasa de detección y retardo por escenario, causal frente a base.
- ``figures/ejemplo_<escenario>.png``: una corrida atacada con el residuo, sus límites, las
  alarmas de ambos detectores y la ventana del ataque.

Es la evaluación de la versión v1 (Fase 6). Las campañas con repeticiones y pruebas
estadísticas (RF-43, RF-45) quedan para la Fase 8.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common.types import LT_102

LABELS = {"causal": "Causal", "threshold": "Base (umbrales)"}
COLORS = {"causal": "#2563eb", "threshold": "#9ca3af"}


def _pct(value: Any) -> str:
    return (
        "—"
        if value is None or (isinstance(value, float) and math.isnan(value))
        else f"{100 * value:.1f} %"
    )


def _num(value: Any, fmt: str = "{:.1f}") -> str:
    return (
        "—"
        if value is None or (isinstance(value, float) and math.isnan(value))
        else fmt.format(value)
    )


def overall(metrics: Any) -> dict[str, dict[str, float]]:
    """Indicadores globales por detector (ataques y corridas normales del dataset)."""
    out = {}
    for kind, part in metrics.groupby("detector"):
        attacks = part[part["attack_id"].astype(str) != ""]
        normal = part[part["scenario"] == "normal"]
        detected = attacks[attacks["detected"] > 0]
        out[kind] = {
            "attacks": int(len(attacks)),
            "dr": float(attacks["detected"].mean()) if len(attacks) else float("nan"),
            "delay_mean_s": float(detected["delay_s"].mean()) if len(detected) else float("nan"),
            "delay_median_s": float(detected["delay_s"].median())
            if len(detected)
            else float("nan"),
            "fpr_normal": float(normal["fpr"].mean()) if len(normal) else float("nan"),
            "false_alarms_per_h_normal": float(normal["false_alarms_per_h"].mean())
            if len(normal)
            else float("nan"),
            "f1_attacks": float(attacks["f1"].mean()) if len(attacks) else float("nan"),
            "identification": float(detected["identification_ok"].mean())
            if "identification_ok" in detected and len(detected)
            else float("nan"),
            "processing_p95_ms": float(part["processing_p95_ms"].max()),
        }
    return out


def plot_dr_delay(summary: Any, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = summary[summary["scenario"] != "normal"]
    scenarios = sorted(data["scenario"].unique())
    x = np.arange(len(scenarios))
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    width = 0.38
    for i, kind in enumerate(("causal", "threshold")):
        part = data[data["detector"] == kind].set_index("scenario").reindex(scenarios)
        axes[0].bar(
            x + (i - 0.5) * width,
            100 * part["dr"].fillna(0),
            width,
            label=LABELS[kind],
            color=COLORS[kind],
        )
        axes[1].bar(
            x + (i - 0.5) * width,
            part["delay_mean_s"].fillna(0),
            width,
            label=LABELS[kind],
            color=COLORS[kind],
        )
    for ax, title, unit in (
        (axes[0], "Tasa de detección", "%"),
        (axes[1], "Retardo medio de detección", "s"),
    ):
        ax.set_xticks(x, [s.replace("_", "\n", 1) for s in scenarios], fontsize=7)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(unit)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylim(0, 105)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)


def plot_example(
    grid: Any, outputs: Any, calibration: Mapping[str, Any], scenario: str, path: Path
) -> bool:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs = grid[grid["scenario"] == scenario]
    if runs.empty:
        return False
    run_id = str(runs["run_id"].iloc[0])
    run = runs[runs["run_id"] == run_id]
    causal = outputs.frames["causal"]
    causal = causal[causal["run_id"] == run_id]
    base = outputs.frames["threshold"]
    base = base[base["run_id"] == run_id]
    stream = f"{LT_102}:{min(calibration['causal']['settings']['horizons'])}"
    lim = calibration["causal"]["limits"][stream]
    t = run["sim_time"].to_numpy(float)
    attacked = run["label"].to_numpy() > 0

    fig, axes = plt.subplots(3, 1, figsize=(10, 6.5), sharex=True, height_ratios=(2, 2, 1))
    axes[0].plot(t, run[LT_102], lw=0.8, label="LT-102 recibido")
    axes[0].plot(t, run["LIC-102.SP"], "--", lw=0.8, color="k", label="Consigna")
    axes[0].set_ylabel("cm")
    axes[1].plot(
        causal["sim_time"], causal[stream], lw=0.7, color=COLORS["causal"], label=f"z {stream}"
    )
    axes[1].axhline(lim["upper"], color="r", lw=0.7, ls=":")
    axes[1].axhline(lim["lower"], color="r", lw=0.7, ls=":", label="Límites calibrados")
    axes[1].set_ylabel("z")
    axes[1].set_ylim(
        max(-15, np.nanmin(causal[stream]) - 1), min(15, np.nanmax(causal[stream]) + 1)
    )
    axes[2].fill_between(
        causal["sim_time"],
        1.0,
        1.8,
        where=causal["alarm"] > 0,
        color=COLORS["causal"],
        step="post",
        label="Alarma causal",
    )
    axes[2].fill_between(
        base["sim_time"],
        0.0,
        0.8,
        where=base["alarm"] > 0,
        color="#6b7280",
        step="post",
        label="Alarma base",
    )
    axes[2].set_yticks([0.4, 1.4], ["Base", "Causal"])
    axes[2].set_ylim(-0.1, 1.9)
    for ax in axes:
        ax.fill_between(
            t,
            0,
            1,
            where=attacked,
            transform=ax.get_xaxis_transform(),
            color="#fca5a5",
            alpha=0.25,
            step="post",
        )
        ax.legend(fontsize=7, loc="upper left")
        ax.grid(alpha=0.3)
    axes[2].set_xlabel("Tiempo simulado [s] (sombreado: ataque)")
    axes[0].set_title(f"{scenario}: residuo del gemelo y alarmas", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)
    return True


def render(
    summary: Any,
    totals: Mapping[str, Mapping[str, float]],
    calibration: Mapping[str, Any],
    data_path: Path,
) -> str:
    causal_info = calibration["causal"]["info"]
    settings = calibration["causal"]["settings"]
    lines = [
        "# Evaluación de los detectores (v1)",
        "",
        f"Dataset: `{data_path}` · generado el {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "## Calibración",
        "",
        f"- Detector causal: horizontes del gemelo {settings['horizons']} pasos, "
        f"CUSUM k = {settings['cusum_k']}, EWMA λ = {settings['ewma_lambda']}, "
        f"retención {settings['hold_s']} s.",
        f"- FPR objetivo {_pct(settings['target_fpr'])}; FPR medido en validación "
        f"{_pct(causal_info.get('val_fpr'))} (nivel por regla "
        f"ε = {causal_info.get('epsilon_per_rule', float('nan')):.2e}).",
        f"- Método base: μ ± {calibration['threshold']['k_sigma']:g}σ y límites operativos; "
        f"FPR en validación {_pct(calibration['threshold'].get('info', {}).get('val_fpr'))}.",
        "",
        "## Resultados globales",
        "",
        "| Indicador | Causal | Base (umbrales) |",
        "|---|---|---|",
    ]
    c, b = totals.get("causal", {}), totals.get("threshold", {})
    rows = (
        ("Ataques evaluados", "attacks", "{:.0f}", False),
        ("Tasa de detección (DR)", "dr", None, True),
        ("Retardo medio [s]", "delay_mean_s", "{:.1f}", False),
        ("Retardo mediano [s]", "delay_median_s", "{:.1f}", False),
        ("FPR en corridas normales", "fpr_normal", None, True),
        ("Falsas alarmas por hora (normales)", "false_alarms_per_h_normal", "{:.1f}", False),
        ("F1 por muestra (corridas atacadas)", "f1_attacks", "{:.3f}", False),
        ("Identificación correcta (ataques detectados)", "identification", None, True),
        ("Tiempo de procesamiento p95 [ms]", "processing_p95_ms", "{:.3f}", False),
    )
    for label, key, fmt, pct in rows:
        fmt_value = _pct if pct else (lambda v, f=fmt: _num(v, f))
        lines.append(f"| {label} | {fmt_value(c.get(key))} | {fmt_value(b.get(key))} |")
    lines += [
        "",
        "## Por escenario",
        "",
        "| Escenario | Detector | DR | Retardo medio [s] | FPR | F1 | AUC | Identificación |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in summary.to_dict("records"):
        lines.append(
            f"| {row['scenario']} | {LABELS.get(row['detector'], row['detector'])} | "
            f"{_pct(row.get('dr'))} | {_num(row.get('delay_mean_s'))} | {_pct(row.get('fpr'))} | "
            f"{_num(row.get('f1'), '{:.3f}')} | {_num(row.get('auc'), '{:.3f}')} | "
            f"{_pct(row.get('identification'))} |"
        )
    lines += [
        "",
        "Notas:",
        "",
        "- DR: un ataque cuenta como detectado si alguna alarma empieza entre su inicio y "
        "10 s después de su fin.",
        "- FPR: fracción de muestras normales en alarma. En las corridas atacadas se excluyen "
        "los 120 s posteriores al ataque (el gemelo de horizonte largo conserva anclas falsas "
        "y el lazo se recupera).",
        "- Identificación: variable más votada por el detector durante sus alarmas dentro de "
        "la ventana del ataque.",
        "",
        "![DR y retardo](figures/dr_retardo.png)",
        "",
        "![Ejemplo](figures/ejemplo_sesgo_lt102.png)",
        "",
    ]
    return "\n".join(lines)


def write_report(
    out_dir: Path,
    grid: Any,
    outputs: Any,
    metrics: Any,
    summary: Any,
    calibration: Mapping[str, Any],
    data_path: Path,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    totals = overall(metrics)
    plot_dr_delay(summary, out_dir / "figures" / "dr_retardo.png")
    for scenario in ("sesgo_lt102", "rampa_lt101", "replay_lt102"):
        plot_example(
            grid, outputs, calibration, scenario, out_dir / "figures" / f"ejemplo_{scenario}.png"
        )
    (out_dir / "report.md").write_text(
        render(summary, totals, calibration, data_path), encoding="utf-8"
    )
    report = {
        "dataset": str(data_path),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall": totals,
        "by_scenario": json.loads(summary.to_json(orient="records")),
        "calibration": {
            "causal": calibration["causal"]["info"],
            "threshold": calibration["threshold"].get("info", {}),
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return report
