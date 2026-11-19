"""Indicadores de una corrida y verificación de sus criterios de aceptación (Fases 3 y 4).

A partir de lo que registraron el monitor (``samples``), el plano de experimento
(``ground_truth``) y los intervalos de ataque calcula:

- **completitud** (RF-25): fracción de pasos de la planta que llegaron al monitor por OPC UA;
- **transparencia** (RF-13, RF-16): fuera de las ventanas de ataque, las muestras recibidas
  coinciden exactamente con lo que publicó la planta (unión por SourceTimestamp, que es el
  instante programado del paso);
- **efecto de cada ataque** (RF-17 a RF-21, RF-24): diferencia entre lo recibido y lo que midió
  el sensor dentro de la ventana — sesgo constante, rampa lineal, replay de la grabación,
  envolvente de sigilo y retardo del primer valor falso;
- **latencias por salto** (RNF-03): planta → gateway, gateway → monitor y extremo a extremo;
- **reloj** (RF-05, RNF-01): pasos atrasados, deriva y tiempo de cómputo por paso;
- **control** (RF-08): error de seguimiento en cada tramo de consigna (los tramos afectados por
  una perturbación legítima o por un ataque se marcan y no cuentan) y desempeño en cada cambio
  de consigna, comparado con el mismo escenario y la misma semilla en modo offline.

Cada criterio vale ``True``, ``False`` o ``None`` (no aplica en esta corrida).

Implementado en la Fase 3; ataques en la Fase 4.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102, AttackEvent, AttackType

STEP_TAGS = (LT_101, LT_102, FT_101)  # se publican en cada paso
EVENT_TAGS = (P_101, SP_102)  # cambian cuando un cliente escribe
MATCH_TOLERANCE_S = 5e-5
"""Tolerancia para unir muestras y pasos por SourceTimestamp.

Las marcas de tiempo OPC UA tienen resolución de 100 ns, pero al pasar de época Unix a DateTime
y de vuelta pueden desplazarse 1 µs; 50 µs es muy inferior a la separación entre pasos
(100 ms en tiempo real, 1 ms incluso a 100×).
"""
SETTLING_MARGIN_S = 500.0  # ≈ tiempo de establecimiento del lazo (455 s, Fase 2)


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


def _windows(events: Iterable[AttackEvent], tag: str, horizon: float) -> list[tuple[float, float]]:
    return [
        (e.t_start, e.t_end if e.t_end is not None else horizon) for e in events if tag in e.targets
    ]


def _inside(t: np.ndarray, windows: list[tuple[float, float]]) -> np.ndarray:
    mask = np.zeros(t.size, dtype=bool)
    for start, end in windows:
        mask |= (t >= start) & (t < end)
    return mask


def merge_tag(
    samples: Any, ground_truth: Any, tag: str, tolerance_s: float = MATCH_TOLERANCE_S
) -> Any:
    """Une las muestras de ``tag`` con el paso de verdad de terreno que les corresponde."""
    import pandas as pd

    gt = ground_truth.assign(_step=np.arange(len(ground_truth))).sort_values("source_ts")
    s = samples[samples["tag"] == tag]
    s = s[np.isfinite(s["source_ts"].to_numpy(dtype=float))].sort_values("source_ts")
    s = s.drop(columns=[c for c in ("sim_time",) if c in s.columns])
    cols = ["source_ts", "_step", "sim_time", f"meas_{tag}", f"true_{tag}"]
    return pd.merge_asof(
        s,
        gt[[c for c in cols if c in gt.columns]],
        on="source_ts",
        direction="nearest",
        tolerance=tolerance_s,
    ).dropna(subset=["_step"])


def data_quality(
    samples: Any,
    ground_truth: Any,
    events: Iterable[AttackEvent] = (),
    tolerance_s: float = MATCH_TOLERANCE_S,
) -> dict[str, Any]:
    events = list(events)
    steps = len(ground_truth)
    horizon = float(ground_truth["sim_time"].max()) + 1.0 if steps else 0.0
    completeness: dict[str, Any] = {}
    transparency: dict[str, Any] = {}
    latencies: dict[str, list[np.ndarray]] = {
        "plant_to_gateway": [],
        "gateway_to_monitor": [],
        "end_to_end": [],
    }
    for tag in STEP_TAGS:
        merged = merge_tag(samples, ground_truth, tag, tolerance_s)
        received = int(merged["_step"].nunique())
        completeness[tag] = {
            "expected": steps,
            "received": received,
            "pct": 100.0 * received / steps if steps else 0.0,
        }
        attacked = _inside(merged["sim_time"].to_numpy(dtype=float), _windows(events, tag, horizon))
        clean = merged[~attacked]
        diff = np.abs(clean["value"].to_numpy() - clean[f"meas_{tag}"].to_numpy())
        transparency[tag] = {
            "compared": int(diff.size),
            "mismatches": int(np.count_nonzero(diff > 0)),
            "max_abs_diff": float(diff.max()) if diff.size else 0.0,
            "in_attack_windows": int(attacked.sum()),
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
    return {
        "steps": steps,
        "completeness": completeness,
        "transparency": transparency,
        "event_samples": {tag: int((samples["tag"] == tag).sum()) for tag in EVENT_TAGS},
        "latency_ms": {hop: _pct(np.concatenate(v)) for hop, v in latencies.items() if v},
    }


# ---------------------------------------------------------------------- efecto de los ataques
def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if x.size < 3 or np.ptp(x) == 0:
        return math.nan, math.nan
    slope, intercept = np.polyfit(x, y, 1)
    residual = y - (slope * x + intercept)
    total = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - float(np.sum(residual**2) / total) if total > 0 else 1.0
    return float(slope), r2


def _replay_expected(merged: Any, start: float, record_s: float, times: np.ndarray) -> np.ndarray:
    rec = merged[(merged["sim_time"] >= start - record_s - 1e-9) & (merged["sim_time"] < start)]
    rec = rec.sort_values("sim_time")
    if rec.empty:
        return np.full(times.size, np.nan)
    offsets = rec["sim_time"].to_numpy() - (start - record_s)
    values = rec[next(c for c in rec.columns if c.startswith("meas_"))].to_numpy()
    position = np.mod(times - start, record_s)
    index = np.clip(np.searchsorted(offsets, position + 1e-9, side="right") - 1, 0, None)
    return values[index]


def attack_effects(
    samples: Any,
    ground_truth: Any,
    events: Iterable[AttackEvent],
    specs: Iterable[Any] = (),
    tolerance_s: float = MATCH_TOLERANCE_S,
) -> list[dict[str, Any]]:
    """Efecto medido de cada ataque sobre cada variable objetivo."""
    import pandas as pd

    stealth = {s.attack_id: s.stealth for s in specs}
    horizon = float(ground_truth["sim_time"].max()) + 1.0 if len(ground_truth) else 0.0
    out = []
    for event in events:
        end = event.t_end if event.t_end is not None else horizon
        for tag in event.targets:
            item: dict[str, Any] = {
                "attack_id": event.attack_id,
                "type": event.type.value,
                "tag": tag,
                "t_start": event.t_start,
                "t_end": end,
            }
            if tag in STEP_TAGS:
                merged = merge_tag(samples, ground_truth, tag, tolerance_s)
                t = merged["sim_time"].to_numpy(dtype=float)
                inside = (t >= event.t_start) & (t < end)
                received = merged["value"].to_numpy(dtype=float)[inside]
                diff = received - merged[f"meas_{tag}"].to_numpy(dtype=float)[inside]
                tw = t[inside]
                item["n"] = int(inside.sum())
                nonzero = np.flatnonzero(np.abs(diff) > 1e-12)
                item["first_effect_s"] = (
                    float(tw[nonzero[0]] - event.t_start) if nonzero.size else None
                )
                item["status_good"] = bool((merged["status"].to_numpy()[inside] == "Good").all())
                spec = stealth.get(event.attack_id)
                if (
                    spec is not None
                    and spec.enabled
                    and spec.envelope is not None
                    and received.size
                ):
                    low, high = spec.envelope
                    item["within_envelope"] = bool(((received >= low) & (received <= high)).all())
                if event.type is AttackType.BIAS and diff.size:
                    expected = float(event.params.get("bias", 0.0))
                    settled = diff[tw >= tw[0] + _ramp_in(expected, spec)]
                    item["expected"] = expected
                    item["median_diff"] = float(np.median(settled)) if settled.size else math.nan
                    item["ok"] = bool(
                        abs(item["median_diff"] - expected) <= 0.01 * max(1.0, abs(expected))
                    )
                elif event.type is AttackType.RAMP and diff.size:
                    slope = float(event.params.get("slope_per_s", 0.0))
                    limit = abs(float(event.params.get("max_deviation", math.inf)))
                    rel = tw - event.t_start
                    linear = np.abs(slope * rel) < 0.98 * limit
                    fit_slope, r2 = _linear_fit(rel[linear], diff[linear])
                    item.update(
                        expected=slope,
                        slope=fit_slope,
                        r2=r2,
                        max_abs_diff=float(np.max(np.abs(diff))),
                        ok=bool(r2 > 0.99 and abs(fit_slope - slope) <= 0.02 * abs(slope)),
                    )
                elif event.type is AttackType.REPLAY and diff.size:
                    record = float(event.params.get("record_s", 0.0))
                    expected = _replay_expected(merged, event.t_start, record, tw)
                    match = np.abs(received - expected) < 1e-9
                    item.update(
                        replayed_fraction=float(match.mean()), ok=bool(match.mean() >= 0.999)
                    )
            elif tag in EVENT_TAGS:
                # Orden alterada en camino a la planta (RF-24): lo aplicado frente a lo escrito
                s = samples[samples["tag"] == tag].sort_values("sim_time")
                gt = ground_truth[["sim_time", f"meas_{tag}"]].sort_values("sim_time")
                merged = pd.merge_asof(gt, s[["sim_time", "value"]], on="sim_time")
                t = merged["sim_time"].to_numpy(dtype=float)
                inside = (t > event.t_start) & (t <= end)
                diff = merged[f"meas_{tag}"].to_numpy()[inside] - merged["value"].to_numpy()[inside]
                item.update(
                    n=int(inside.sum()),
                    median_diff=float(np.nanmedian(diff)) if diff.size else math.nan,
                )
                if event.type is AttackType.BIAS:
                    item["expected"] = float(event.params.get("bias", 0.0))
                    item["ok"] = bool(abs(item["median_diff"] - item["expected"]) <= 0.05)
            out.append(item)
    return out


def _ramp_in(bias: float, spec: Any) -> float:
    """Tiempo que tarda el sesgo en alcanzarse con el límite de tasa de sigilo."""
    rate = getattr(spec, "max_rate_per_s", None) if spec is not None and spec.enabled else None
    return abs(bias) / rate + 1e-6 if rate else 0.0


def attack_criteria(
    effects: list[dict[str, Any]], transparency: Mapping[str, Any]
) -> dict[str, Any]:
    def by_type(kind: str) -> list[dict[str, Any]]:
        return [e for e in effects if e["type"] == kind and "ok" in e]

    def verdict(items: list[dict[str, Any]]) -> bool | None:
        return all(i["ok"] for i in items) if items else None

    envelope = [e["within_envelope"] for e in effects if "within_envelope" in e]
    delays = [e["first_effect_s"] for e in effects if e.get("first_effect_s") is not None]
    good = [e["status_good"] for e in effects if "status_good" in e]
    return {
        "RF-16 transparente fuera de las ventanas de ataque": all(
            v["mismatches"] == 0 for v in transparency.values()
        )
        if transparency
        else None,
        "RF-16 valores falsos con StatusCode Good": all(good) if good else None,
        "RF-17 sesgo recibido = b": verdict(by_type("bias")),
        "RF-18 rampa lineal (R² > 0,99)": verdict(by_type("ramp")),
        "RF-19 replay reproduce la ventana grabada": verdict(by_type("replay")),
        "RF-20 valores falsos dentro de la envolvente": all(envelope) if envelope else None,
        "RF-21 primer valor falso ≤ 1 periodo tras el inicio": all(d <= 0.5 for d in delays)
        if delays
        else None,
    }


# ---------------------------------------------------------------------- control
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


def attack_windows(
    events: Iterable[AttackEvent], horizon: float, margin_s: float = SETTLING_MARGIN_S
) -> list[tuple[float, float]]:
    """Intervalos en que un ataque (y la recuperación posterior) aleja h2 de la consigna."""
    return [(e.t_start, (e.t_end if e.t_end is not None else horizon) + margin_s) for e in events]


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
    cuya ventana coincide con una perturbación legítima o un ataque (o con su recuperación) se
    marca como ``perturbado``: su error no se atribuye al lazo.
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


def _control_section(
    gt: Any, scenario: Any, events: list[AttackEvent], reference: Any | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    times = [t for t, _ in scenario.setpoint_profile]
    values = [v for _, v in scenario.setpoint_profile]
    t_end = float(gt["sim_time"].iloc[-1])
    current = control_performance(gt["sim_time"], gt[f"true_{LT_102}"], times, values, t_end)
    disturbed = disturbance_windows(scenario.disturbances) + attack_windows(events, t_end)
    tracking = setpoint_tracking(
        gt["sim_time"], gt[f"true_{LT_102}"], gt[f"true_{SP_102}"], disturbed=disturbed
    )
    section: dict[str, Any] = {"tracking": tracking, "steps": current}
    clean = [seg for seg in tracking if not seg["perturbado"]]
    criteria: dict[str, Any] = {
        "RF-08 regulación de h2 en tramos sin perturbación ni ataque (error < 2 %)": (
            all(seg["error_pct"] < 2.0 for seg in clean) if clean else None
        )
    }
    if reference is not None:
        offline = control_performance(
            reference["sim_time"], reference[f"true_{LT_102}"], times, values, t_end
        )
        section["offline_steps"] = offline
        pairs = [
            (n["iae"], o["iae"])
            for n, o in zip(current, offline, strict=False)
            if n["iae"] and o["iae"]
        ]
        criteria["RF-08 lazo en red equivalente al offline (IAE ± 5 %)"] = (
            all(abs(n - o) / o < 0.05 for n, o in pairs) if pairs else None
        )
    return section, criteria


# ---------------------------------------------------------------------- resúmenes
def summarize_network_run(
    run_dir: Path,
    component_stats: Mapping[str, Any],
    config: Mapping[str, Any],
    scenario: Any,
    seed: int,
    duration_s: float,
    status: str,
    events: list[AttackEvent] | None = None,
) -> dict[str, Any]:
    from fdisim.orchestration.offline import simulate_offline

    run_dir = Path(run_dir)
    events = list(events or [])
    sim = config["simulation"]
    dt = float(sim["dt_s"])
    publishing_ms = float(config["opcua"]["subscription"]["publishing_interval_ms"])
    samples = _read_table(run_dir, "samples")
    gt = _read_table(run_dir, "ground_truth")
    plant = component_stats.get("plant_server") or {}

    summary: dict[str, Any] = {
        "status": status,
        "mode": "network",
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
        "attacks": [_event_dict(e) for e in events],
    }
    if samples is None or gt is None or gt.empty:
        summary["criteria"] = {}
        return summary

    quality = data_quality(samples, gt, events)
    summary.update(quality)
    effects = attack_effects(samples, gt, events, scenario.attacks)
    summary["attack_effects"] = effects

    t_end = float(gt["sim_time"].iloc[-1])
    reference = simulate_offline(config, scenario, seed, t_end).ground_truth
    control, control_criteria = _control_section(gt, scenario, events, reference)
    summary["control"] = control

    clock = plant.get("clock", {})
    e2e = quality["latency_ms"].get("end_to_end", {})
    min_completeness = min(v["pct"] for v in quality["completeness"].values())
    criteria: dict[str, Any] = {
        "RF-05 deriva del reloj < 1 %": clock.get("drift_pct", math.inf) < 1.0,
        "RF-06 verdad de terreno en el 100 % de los pasos": len(gt) == summary["expected_steps"],
        "RF-13 gateway transparente (fuera de los ataques)": all(
            v["mismatches"] == 0 for v in quality["transparency"].values()
        ),
        "RF-25 completitud ≥ 99,9 %": min_completeness >= 99.9,
        "RNF-01 cómputo por paso p99 < 10 % de Δt": plant.get("compute_ms", {}).get("p99", math.inf)
        < 100.0 * dt,
        "RNF-03 latencia extremo a extremo p95 ≤ 2 × publicación (en tiempo de pared)": e2e.get(
            "p95", math.inf
        )
        <= 2 * publishing_ms,
    }
    criteria.update(control_criteria)
    if events:
        attack = attack_criteria(effects, {})
        attack.pop("RF-16 transparente fuera de las ventanas de ataque")
        criteria.update(attack)
    summary["criteria"] = criteria
    return summary


def summarize_offline_run(
    result: Any, config: Mapping[str, Any], scenario: Any, seed: int, duration_s: float
) -> dict[str, Any]:
    samples, gt, events = result.samples, result.ground_truth, list(result.events)
    quality = data_quality(samples, gt, events, tolerance_s=1e-9)
    effects = attack_effects(samples, gt, events, scenario.attacks, tolerance_s=1e-9)
    control, control_criteria = _control_section(gt, scenario, events, None)
    criteria = {
        "RF-06 verdad de terreno en el 100 % de los pasos": len(gt) == result.stats["steps"],
        "RNF-04 offline ≥ 100× tiempo real": result.stats["speedup"] >= 100.0,
    }
    criteria.update(attack_criteria(effects, quality["transparency"]))
    criteria.update(control_criteria)
    return {
        "status": "completed",
        "mode": "offline",
        "scenario": scenario.name,
        "seed": seed,
        "duration_s": duration_s,
        "simulation": result.stats,
        "attacks": [_event_dict(e) for e in events],
        "labels": {
            "samples_under_attack": int(samples["label"].sum()),
            "steps_under_attack": int(gt["attack_active"].sum()),
        },
        "transparency": quality["transparency"],
        "event_samples": quality["event_samples"],
        "attack_effects": effects,
        "control": control,
        "criteria": criteria,
    }


def _event_dict(event: AttackEvent) -> dict[str, Any]:
    return {
        "attack_id": event.attack_id,
        "type": event.type.value,
        "targets": list(event.targets),
        "t_start": event.t_start,
        "t_end": event.t_end,
        "params": dict(event.params),
    }
