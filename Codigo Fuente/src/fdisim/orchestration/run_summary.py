"""Indicadores de una corrida en red y verificación de sus criterios de aceptación (Fase 3).

A partir de lo que registraron el monitor (``samples``) y el plano de experimento
(``ground_truth``) calcula:

- **completitud** (RF-25): fracción de pasos de la planta que llegaron al monitor por OPC UA;
- **transparencia** del gateway (RF-13): las muestras recibidas coinciden exactamente con lo que
  publicó la planta (unión por SourceTimestamp, que es el instante programado del paso);
- **latencias por salto** (RNF-03): planta → gateway (ServerTimestamp del gateway −
  SourceTimestamp), gateway → monitor (recepción − ServerTimestamp) y extremo a extremo;
- **reloj** (RF-05, RNF-01): pasos atrasados, deriva y tiempo de cómputo por paso;
- **control** (RF-08): error de seguimiento en cada tramo de consigna (los tramos afectados por
  una perturbación legítima se marcan y no cuentan) y desempeño en cada cambio de consigna,
  comparado con el mismo escenario y la misma semilla en modo offline (sin red).

Cada criterio vale ``True``, ``False`` o ``None`` (no aplica en esta corrida, p. ej. una corrida
corta sin cambios de consigna).

Implementado en la Fase 3.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102

STEP_TAGS = (LT_101, LT_102, FT_101)  # se publican en cada paso
EVENT_TAGS = (P_101, SP_102)  # cambian cuando un cliente escribe


def _read_table(run_dir: Path, name: str) -> Any:
    import pandas as pd

    for suffix, reader in ((".parquet", pd.read_parquet), (".csv", pd.read_csv)):
        path = run_dir / f"{name}{suffix}"
        if path.is_file():
            return reader(path)
    return None


def _pct(values: Any) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"n": 0}
    return {
        "n": int(arr.size),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(arr.max()),
    }


MATCH_TOLERANCE_S = 5e-5
"""Tolerancia para unir muestras y pasos por SourceTimestamp.

Las marcas de tiempo OPC UA tienen resolución de 100 ns, pero al pasar de época Unix a DateTime
y de vuelta pueden desplazarse 1 µs; 50 µs es muy inferior a la separación entre pasos
(100 ms en tiempo real, 1 ms incluso a 100×).
"""


def data_quality(
    samples: Any, ground_truth: Any, tolerance_s: float = MATCH_TOLERANCE_S
) -> dict[str, Any]:
    import pandas as pd

    steps = len(ground_truth)
    gt = ground_truth.assign(_step=np.arange(steps)).sort_values("source_ts")
    completeness: dict[str, Any] = {}
    transparency: dict[str, Any] = {}
    latencies: dict[str, list[np.ndarray]] = {
        "plant_to_gateway": [],
        "gateway_to_monitor": [],
        "end_to_end": [],
    }
    for tag in STEP_TAGS:
        s = samples[samples["tag"] == tag]
        s = s[np.isfinite(s["source_ts"].to_numpy(dtype=float))].sort_values("source_ts")
        merged = pd.merge_asof(
            s,
            gt[["source_ts", "_step", f"meas_{tag}"]],
            on="source_ts",
            direction="nearest",
            tolerance=tolerance_s,
        ).dropna(subset=["_step"])
        received = int(merged["_step"].nunique())
        completeness[tag] = {
            "expected": steps,
            "received": received,
            "pct": 100.0 * received / steps if steps else 0.0,
        }
        diff = np.abs(merged["value"].to_numpy() - merged[f"meas_{tag}"].to_numpy())
        transparency[tag] = {
            "compared": int(diff.size),
            "mismatches": int(np.count_nonzero(diff > 0)),
            "max_abs_diff": float(diff.max()) if diff.size else 0.0,
        }
        latencies["plant_to_gateway"].append(
            1000 * (merged["server_ts"].to_numpy() - merged["source_ts"].to_numpy())
        )
        latencies["gateway_to_monitor"].append(
            1000 * (merged["received_ts"].to_numpy() - merged["server_ts"].to_numpy())
        )
        latencies["end_to_end"].append(
            1000 * (merged["received_ts"].to_numpy() - merged["source_ts"].to_numpy())
        )
    events = {tag: int((samples["tag"] == tag).sum()) for tag in EVENT_TAGS}
    return {
        "steps": steps,
        "completeness": completeness,
        "transparency": transparency,
        "event_samples": events,
        "latency_ms": {hop: _pct(np.concatenate(v)) for hop, v in latencies.items() if v},
    }


def control_performance(
    t: Any, y: Any, change_times: list[float], values: list[float], t_end: float
) -> list[dict[str, Any]]:
    from fdisim.control.performance import step_metrics

    out = []
    bounds = [*change_times[1:], t_end]
    for t_step, sp, nxt in zip(change_times, values, bounds, strict=True):
        if t_step <= 0 or t_step >= t_end:
            continue
        metrics = step_metrics(np.asarray(t), np.asarray(y), t_step, sp, t_end=nxt)
        out.append(
            {
                k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                for k, v in metrics.as_dict().items()
            }
        )
    return out


SETTLING_MARGIN_S = 500.0  # ≈ tiempo de establecimiento del lazo (455 s, Fase 2)


def disturbance_windows(
    disturbances: Any, margin_s: float = SETTLING_MARGIN_S
) -> list[tuple[float, float]]:
    """Intervalos en que una perturbación legítima (no el ruido) aleja h2 de la consigna."""
    out = []
    for item in disturbances or ():
        if item.get("type") == "process_noise":
            continue
        start = float(item.get("t_s", 0.0))
        out.append((start, start + float(item.get("duration_s", 0.0)) + margin_s))
    return out


def setpoint_tracking(
    t: Any,
    y: Any,
    setpoint: Any,
    min_segment_s: float = 500.0,
    disturbed: list[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Error de seguimiento en cada tramo de consigna constante (criterio de RF-08).

    Usa la consigna realmente vigente (incluye cambios desde la HMI). Se evalúa el último 20 %
    de cada tramo (al menos 10 s): el primero siempre (la planta arranca en equilibrio) y los
    demás si duran ≥ ``min_segment_s``, tiempo suficiente para establecerse (≈ 455 s). Un tramo
    cuya ventana coincide con una perturbación legítima (o con su recuperación) se marca como
    ``perturbado``: su error no se atribuye al lazo.
    """
    t, y, sp = (np.asarray(v, dtype=float) for v in (t, y, setpoint))
    if t.size == 0:
        return []
    edges = np.flatnonzero(np.diff(sp) != 0) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [t.size]))
    out = []
    for i, (a, b) in enumerate(zip(starts, ends, strict=True)):
        length = t[b - 1] - t[a]
        if i > 0 and length < min_segment_s:
            continue
        window = max(0.2 * length, min(10.0, length))
        w0, w1 = t[b - 1] - window, t[b - 1]
        mask = (t >= w0) & (np.arange(t.size) >= a) & (np.arange(t.size) < b)
        error = abs(float(y[mask].mean()) - sp[a]) / sp[a] * 100.0
        out.append(
            {
                "t_start": float(t[a]),
                "t_end": float(w1),
                "setpoint": float(sp[a]),
                "error_pct": error,
                "perturbado": any(s < w1 and e > w0 for s, e in disturbed or ()),
            }
        )
    return out


def offline_reference(
    config: Mapping[str, Any], scenario: Any, seed: int, duration_s: float
) -> dict[str, Any]:
    from fdisim.orchestration.offline import prepare_closed_loop, run_closed_loop

    loop = prepare_closed_loop(config, scenario, seed=seed)
    result = run_closed_loop(loop, duration_s)
    return {"t": result.t, "h2": result.true[LT_102]}


def summarize_network_run(
    run_dir: Path,
    component_stats: Mapping[str, Any],
    config: Mapping[str, Any],
    scenario: Any,
    seed: int,
    duration_s: float,
    status: str,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    sim = config["simulation"]
    dt = float(sim["dt_s"])
    publishing_ms = float(config["opcua"]["subscription"]["publishing_interval_ms"])
    samples = _read_table(run_dir, "samples")
    gt = _read_table(run_dir, "ground_truth")
    plant = component_stats.get("plant_server") or {}

    summary: dict[str, Any] = {
        "status": status,
        "scenario": scenario.name,
        "seed": seed,
        "duration_s": duration_s,
        "time_scale": float(sim["time_scale"]),
        "security": dict(config["opcua"]["security"]),
        "expected_steps": round(duration_s / dt),
        "plant": plant,
        "gateway": component_stats.get("gateway"),
        "controller": component_stats.get("controller"),
        "monitor": component_stats.get("monitor"),
    }
    if samples is None or gt is None or gt.empty:
        summary["criteria"] = {}
        return summary

    quality = data_quality(samples, gt)
    summary.update(quality)

    times = [t for t, _ in scenario.setpoint_profile]
    values = [v for _, v in scenario.setpoint_profile]
    t_end = float(gt["sim_time"].iloc[-1])
    network = control_performance(gt["sim_time"], gt[f"true_{LT_102}"], times, values, t_end)
    reference = offline_reference(config, scenario, seed, t_end)
    offline = control_performance(reference["t"], reference["h2"], times, values, t_end)
    tracking = setpoint_tracking(
        gt["sim_time"],
        gt[f"true_{LT_102}"],
        gt[f"true_{SP_102}"],
        disturbed=disturbance_windows(scenario.disturbances),
    )
    summary["control"] = {"tracking": tracking, "network": network, "offline": offline}
    clean = [seg for seg in tracking if not seg["perturbado"]]
    iae_pairs = [
        (n["iae"], o["iae"])
        for n, o in zip(network, offline, strict=False)
        if n["iae"] and o["iae"]
    ]

    clock = plant.get("clock", {})
    e2e = quality["latency_ms"].get("end_to_end", {})
    min_completeness = min(v["pct"] for v in quality["completeness"].values())
    summary["criteria"] = {
        "RF-05 deriva del reloj < 1 %": clock.get("drift_pct", math.inf) < 1.0,
        "RF-06 verdad de terreno en el 100 % de los pasos": len(gt) == summary["expected_steps"],
        "RF-13 gateway transparente": all(
            v["mismatches"] == 0 for v in quality["transparency"].values()
        ),
        "RF-25 completitud ≥ 99,9 %": min_completeness >= 99.9,
        "RNF-01 cómputo por paso p99 < 10 % de Δt": plant.get("compute_ms", {}).get("p99", math.inf)
        < 100.0 * dt,
        "RNF-03 latencia extremo a extremo p95 ≤ 2 × publicación": e2e.get("p95", math.inf)
        <= 2 * publishing_ms,
        "RF-08 regulación de h2 en tramos sin perturbación (error < 2 %)": (
            all(seg["error_pct"] < 2.0 for seg in clean) if clean else None
        ),
        "RF-08 lazo en red equivalente al offline (IAE ± 5 %)": (
            all(abs(n - o) / o < 0.05 for n, o in iae_pairs) if iae_pairs else None
        ),
    }
    return summary
