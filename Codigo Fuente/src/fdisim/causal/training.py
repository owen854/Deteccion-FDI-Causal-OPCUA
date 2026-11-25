"""Construcción del modelo causal de referencia (RF-28 a RF-32; comando ``fdisim train``).

Flujo, sobre el dataset de entrenamiento (solo operación normal) y el de validación:

1. Grafo físico a priori (RF-28).
2. Descubrimiento causal con PCMCI+ y Granger condicional en dos resoluciones: la rejilla de
   detección (0,5 s) y la serie promediada por bloques (5 s por defecto), que reduce el ruido
   de medición (RF-29).
3. Sensibilidad de los grafos aprendidos a ``tau_max``, ``alpha`` y la resolución.
4. Comparación de cada grafo aprendido con el físico (SHD, precisión y exhaustividad) y
   consolidación del grafo de referencia con decisiones justificadas (RF-30).
5. Ajuste del SCM físico-informado y del SCM por regresión, estadísticas de los residuos y
   validación: RMSE a un paso ≤ 2σ del sensor y parámetros dentro de ±10 % (RF-31).
6. Persistencia del modelo con su manifiesto (RF-32), reporte (``report.md`` y ``report.json``)
   y figuras.

Implementado en la Fase 5.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.causal.discovery import DiscoveredLink, run_granger, run_pcmci
from fdisim.causal.graph_compare import GRID_DECISIONS, compare, consolidate, discovered_edges
from fdisim.causal.prior_graph import PHYSICAL_LINKS, build_prior_graph, edge_set, export_graph
from fdisim.causal.scm import ENDOGENOUS, PhysicsInformedSCM, RegressionSCM
from fdisim.common.types import FT_101, LT_101, LT_102, P_101

THRESHOLD_K_SIGMA = 3.0  # umbral inicial de los residuos a un paso (la Fase 6 lo calibra)
SENSITIVITY_TAU = (1, 2, 3, 5)
SENSITIVITY_ALPHA = (0.001, 0.01, 0.05)


def _say(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _load(path: Path) -> Any:
    import pandas as pd

    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    if "label" in frame.columns and int(frame["label"].sum()) > 0:
        raise ValueError(
            f"{path.name} contiene muestras bajo ataque: el modelo de referencia se ajusta "
            "solo con operación normal"
        )
    return frame


def sensor_sigmas(config: Mapping[str, Any]) -> dict[str, float]:
    sensors = config["plant"].get("sensors", {})
    return {tag: float(cfg.get("noise_std", 0.0)) for tag, cfg in sensors.items()}


def nominal_parameters(config: Mapping[str, Any]) -> dict[str, float]:
    plant, control = config["plant"], config["control"]
    return {
        "a1": float(plant["tank1"]["outlet_area_cm2"]),
        "a2": float(plant["tank2"]["outlet_area_cm2"]),
        "kp": float(plant["pump"]["gain_cm3_s_per_pct"]),
        "pump_tau": float(plant["pump"]["time_constant_s"]),
        "kc": float(control["kp"]),
        "ki": float(control["ki"]),
    }


def _links_dict(links: Sequence[DiscoveredLink]) -> list[dict[str, Any]]:
    return [asdict(link) for link in links]


def run_discovery(
    train: Any, tau_max: int, alpha: float, coarse_block: int, coarse_tau: int
) -> dict[str, list[DiscoveredLink]]:
    period = float(np.median(np.diff(train["sim_time"].to_numpy()[:100])))
    coarse = f"{period * coarse_block:g} s"
    fine = f"{period:g} s"
    return {
        f"PCMCI+ {fine}": run_pcmci(train, tau_max, alpha, block=1),
        f"Granger {fine}": run_granger(train, tau_max, alpha, block=1),
        f"PCMCI+ {coarse}": run_pcmci(train, coarse_tau, alpha, block=coarse_block),
        f"Granger {coarse}": run_granger(train, coarse_tau, alpha, block=coarse_block),
    }


def sensitivity(
    train: Any, blocks: Sequence[int], prior_edges: set, progress: Callable[[str], None] | None
) -> list[dict[str, Any]]:
    rows = []
    for block in blocks:
        for tau in SENSITIVITY_TAU:
            for alpha in SENSITIVITY_ALPHA:
                for method, runner in (("PCMCI+", run_pcmci), ("Granger", run_granger)):
                    started = time.perf_counter()
                    links = runner(train, tau, alpha, block=block)
                    metrics = compare(prior_edges, discovered_edges(links))
                    rows.append(
                        {
                            "method": method,
                            "block": block,
                            "tau_max": tau,
                            "alpha": alpha,
                            "seconds": time.perf_counter() - started,
                            **metrics,
                        }
                    )
        _say(progress, f"Sensibilidad con bloques de {block} muestra(s) completada")
    return rows


def train_causal_model(
    train_path: Path,
    out_dir: Path,
    *,
    val_path: Path | None = None,
    config_path: Path | None = None,
    tau_max: int = 3,
    alpha: float = 0.01,
    coarse_block: int = 10,
    coarse_tau: int = 2,
    with_sensitivity: bool = True,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Construye, valida y guarda el modelo causal; devuelve la ruta de su manifiesto."""
    from fdisim.causal.model_store import save_model
    from fdisim.common.config import load_config
    from fdisim.data.storage import sha256_file

    train_path = Path(train_path)
    val_path = Path(val_path) if val_path else train_path.with_name("val.parquet")
    out_dir = Path(out_dir)
    config = load_config(config_path).to_dict()
    train = _load(train_path)
    val = _load(val_path) if val_path.is_file() else None
    _say(progress, f"Entrenamiento: {train['run_id'].nunique()} corridas, {len(train)} filas")

    prior = build_prior_graph(PHYSICAL_LINKS)
    prior_edges = edge_set(PHYSICAL_LINKS)

    _say(progress, "Descubrimiento causal (PCMCI+ y Granger)…")
    started = time.perf_counter()
    discovered = run_discovery(train, tau_max, alpha, coarse_block, coarse_tau)
    discovery_s = time.perf_counter() - started
    metrics_vs_prior = {
        name: compare(prior_edges, discovered_edges(links)) for name, links in discovered.items()
    }

    sens: list[dict[str, Any]] = []
    if with_sensitivity:
        _say(progress, "Análisis de sensibilidad (τ_max, α y resolución)…")
        sens = sensitivity(train, (1, coarse_block), prior_edges, progress)

    consolidation = consolidate(PHYSICAL_LINKS, discovered, GRID_DECISIONS)
    reference = consolidation.links
    reference_edges = edge_set(reference)
    metrics_vs_reference = {
        name: compare(reference_edges, discovered_edges(links))
        for name, links in discovered.items()
    }
    graph = build_prior_graph(reference)

    _say(progress, "Ajuste del SCM físico-informado y del SCM por regresión…")
    physics = PhysicsInformedSCM.from_config(config).fit(train)
    regression = RegressionSCM(reference).fit(train)
    sigmas = sensor_sigmas(config)
    evaluation = val if val is not None else train
    validation = {
        "dataset": "val" if val is not None else "train",
        "physics_informed": physics.rmse(evaluation),
        "regression": regression.rmse(evaluation),
        "limit_2sigma": {tag: 2 * sigmas[tag] for tag in ENDOGENOUS if tag in sigmas},
    }
    parameters = physics.parameter_report(nominal_parameters(config))
    criteria = {
        "RF-28 grafo físico exportable": True,
        "RF-29 ambos métodos producen grafos con retardo y valor p": all(
            discovered[name] for name in discovered
        ),
        "RF-31 RMSE a un paso ≤ 2σ del sensor (validación)": all(
            validation["physics_informed"][tag] <= limit
            for tag, limit in validation["limit_2sigma"].items()
        ),
        "RF-31 parámetros dentro de ±10 % de los nominales": all(
            abs(row["error_pct"]) <= 10.0 for row in parameters
        ),
    }
    thresholds = {
        "kind": "one_step_k_sigma",
        "k_sigma": THRESHOLD_K_SIGMA,
        "per_tag": {
            tag: THRESHOLD_K_SIGMA * stats.std for tag, stats in physics.residual_stats.items()
        },
    }
    metadata = {
        "dataset": {
            "train": str(train_path),
            "train_sha256": sha256_file(train_path),
            "val": str(val_path) if val is not None else None,
            "val_sha256": sha256_file(val_path) if val is not None else None,
            "train_runs": int(train["run_id"].nunique()),
            "train_rows": int(len(train)),
        },
        "period_s": float(physics.params.dt),
        "discovery": {
            "tau_max": tau_max,
            "alpha": alpha,
            "coarse_block": coarse_block,
            "coarse_tau": coarse_tau,
        },
        "validation_rmse": validation,
        "criteria": criteria,
    }
    manifest = save_model(physics, graph, thresholds, out_dir, metadata)
    (out_dir / "scm_regression.json").write_text(
        json.dumps(regression.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = {
        "discovery_seconds": discovery_s,
        "discovered": {name: _links_dict(links) for name, links in discovered.items()},
        "metrics_vs_physical": metrics_vs_prior,
        "metrics_vs_reference": metrics_vs_reference,
        "sensitivity": sens,
        "consolidation": consolidation.table,
        "reference_links": [asdict(link) for link in reference],
        "parameters": parameters,
        "residual_stats": {k: asdict(v) for k, v in physics.residual_stats.items()},
        "regression_residual_stats": {k: asdict(v) for k, v in regression.residual_stats.items()},
        "validation_rmse": validation,
        "criteria": criteria,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    figures = out_dir / "figures"
    figures.mkdir(exist_ok=True)
    plot_reference_graph(reference, figures / "grafo_referencia.png")
    plot_residuals(physics, evaluation, sigmas, figures / "residuos_validacion.png")
    (out_dir / "report.md").write_text(render_report(report, metadata), encoding="utf-8")
    export_graph(prior, out_dir / "graph_physical.graphml")  # grafo a priori, para comparar
    _say(progress, f"Modelo guardado en {out_dir}")
    if val is not None:  # Fase 6: calibración de los detectores con el mismo dataset (RF-34)
        from fdisim.detection.pipeline import calibrate_detectors

        calibrate_detectors(
            out_dir,
            config,
            train,
            val,
            dataset={"train": str(train_path), "val": str(val_path)},
            progress=progress,
        )
    return manifest


# ---------------------------------------------------------------------- figuras
def plot_reference_graph(links: Sequence[Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    positions = {
        "LIC-102.SP": (0.0, 1.0),
        P_101: (1.0, 1.0),
        FT_101: (2.0, 1.0),
        LT_101: (3.0, 0.4),
        LT_102: (2.0, -0.2),
    }
    lags: dict[tuple[str, str], list[int]] = {}
    for link in links:
        lags.setdefault((link.source, link.target), []).append(link.lag)
    graph = nx.DiGraph()
    graph.add_nodes_from(positions)
    for (s, t), values in lags.items():
        graph.add_edge(s, t, label=",".join(str(v) for v in sorted(values)))
    fig, ax = plt.subplots(figsize=(8, 4.6))
    nx.draw_networkx_nodes(
        graph, positions, node_size=2300, node_color="#dbeafe", edgecolors="#1e3a8a", ax=ax
    )
    nx.draw_networkx_labels(graph, positions, font_size=9, ax=ax)
    others = [(s, t) for s, t in graph.edges if s != t]
    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=others,
        arrowsize=18,
        node_size=2300,
        connectionstyle="arc3,rad=0.12",
        edge_color="#334155",
        ax=ax,
    )
    nx.draw_networkx_edge_labels(
        graph,
        positions,
        edge_labels={(s, t): f"τ={graph[s][t]['label']}" for s, t in others},
        font_size=8,
        label_pos=0.45,
        ax=ax,
    )
    for node in positions:
        if graph.has_edge(node, node):
            x, y = positions[node]
            ax.annotate(
                f"↻ τ={graph[node][node]['label']}",
                (x + 0.2, y - 0.03),
                ha="left",
                fontsize=8,
                color="#7c2d12",
            )
    ax.set_title("Grafo causal de referencia (retardos τ en pasos de 0,5 s)", fontsize=11)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_residuals(model: Any, data: Any, sigmas: Mapping[str, float], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    residuals = model.residuals(data)
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.2))
    for ax, tag in zip(axes, ENDOGENOUS, strict=True):
        r = residuals[tag].dropna().to_numpy()
        ax.hist(r, bins=60, color="#3b82f6", alpha=0.85)
        rmse = float(np.sqrt(np.mean(r**2)))
        limit = 2 * sigmas[tag] if tag in sigmas else None
        ax.set_title(f"{tag}\nRMSE {rmse:.3f}" + (f" (≤ {limit:.2f})" if limit else ""), fontsize=9)
        ax.tick_params(labelsize=7)
    fig.suptitle("Residuos a un paso del SCM físico-informado en validación", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------- reporte
def _fmt_found(found: Mapping[str, list[int]]) -> str:
    return "; ".join(f"{m}: {','.join(map(str, sorted(set(v))))}" for m, v in found.items()) or "—"


def render_report(report: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    lines = [
        "# Modelo causal de referencia: reporte comparativo",
        "",
        f"Dataset de entrenamiento: `{metadata['dataset']['train']}` "
        f"({metadata['dataset']['train_runs']} corridas, {metadata['dataset']['train_rows']} "
        f"filas, rejilla de {metadata['period_s']:g} s). Validación: "
        f"`{metadata['dataset']['val']}`.",
        "",
        "## Comparación con el grafo físico",
        "",
        "| Método | Enlaces | SHD | Precisión | Exhaustividad | Precisión sin retardo | "
        "Exhaustividad sin retardo |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in report["metrics_vs_physical"].items():
        lines.append(
            f"| {name} | {m['edges']} | {m['shd']} | {m['precision']:.2f} | {m['recall']:.2f} "
            f"| {m['precision_sin_retardo']:.2f} | {m['recall_sin_retardo']:.2f} |"
        )
    lines += [
        "",
        "## Consolidación del grafo de referencia",
        "",
        "| Enlace | Físico (retardos) | Referencia (retardos) | Encontrado por | Justificación |",
        "|---|---|---|---|---|",
    ]
    for row in report["consolidation"]:
        lines.append(
            f"| {row['source']} → {row['target']} | "
            f"{','.join(map(str, row['physical_lags'])) or '—'} | "
            f"{','.join(map(str, row['reference_lags'])) or '—'} | {_fmt_found(row['found_by'])} "
            f"| {row['reason']} |"
        )
    lines += [
        "",
        "## Parámetros identificados (SCM físico-informado)",
        "",
        "| Parámetro | Identificado | Nominal | Error |",
        "|---|---|---|---|",
    ]
    for row in report["parameters"]:
        lines.append(
            f"| {row['parameter']} | {row['identified']:.5g} | {row['nominal']:.5g} | "
            f"{row['error_pct']:+.2f} % |"
        )
    val = report["validation_rmse"]
    lines += [
        "",
        f"## RMSE a un paso ({val['dataset']})",
        "",
        "| Variable | Físico-informado | Regresión | Límite 2σ |",
        "|---|---|---|---|",
    ]
    for tag in ENDOGENOUS:
        limit = val["limit_2sigma"].get(tag)
        lines.append(
            f"| {tag} | {val['physics_informed'][tag]:.4f} | {val['regression'][tag]:.4f} | "
            f"{f'{limit:.2f}' if limit is not None else '—'} |"
        )
    if report["sensitivity"]:
        lines += [
            "",
            "## Sensibilidad (frente al grafo físico, sin retardo)",
            "",
            "| Método | Bloque | τ_max | α | Enlaces | SHD | Precisión | Exhaustividad |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in report["sensitivity"]:
            lines.append(
                f"| {row['method']} | {row['block']} | {row['tau_max']} | {row['alpha']} | "
                f"{row['edges']} | {row['shd']} | {row['precision_sin_retardo']:.2f} | "
                f"{row['recall_sin_retardo']:.2f} |"
            )
    lines += ["", "## Criterios", ""]
    lines += [f"- [{'x' if ok else ' '}] {name}" for name, ok in report["criteria"].items()]
    return "\n".join(lines) + "\n"
