"""Calibración y sintonía del lazo de nivel en modo offline (Fase 2; RF-01 a RF-04, RF-07, RNF-01).

Simula un escenario (por defecto ``normal.yaml``: cambios de consigna y perturbaciones
legítimas), evalúa cada escalón de consigna con los criterios de RF-07 (sobrepaso < 20 %,
error estacionario < 2 %), mide el costo de cómputo por paso (RNF-01: < 10 % de Δt) y guarda
una figura y un resumen en ``results/fase2/``.

Uso::

    python scripts/calibrar_lazo.py                       # ganancias de default.yaml
    python scripts/calibrar_lazo.py --kp 4 --ki 0.04      # probar otras ganancias
    python scripts/calibrar_lazo.py --barrido             # barrido de Kp y Ki (integrador rk4)
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fdisim.common import paths  # noqa: E402
from fdisim.common.config import load_scenario, load_yaml  # noqa: E402
from fdisim.common.types import LT_101, LT_102, P_101  # noqa: E402
from fdisim.control.performance import step_metrics  # noqa: E402
from fdisim.orchestration.offline import prepare_closed_loop, run_closed_loop  # noqa: E402

OVERSHOOT_MAX, SSE_MAX = 20.0, 2.0


def evaluate(config: dict, scenario, overrides: dict, integrator: str | None, seed: int | None):
    loop = prepare_closed_loop(config, scenario, seed, integrator, overrides)
    result = run_closed_loop(loop, scenario.duration_s)
    changes = loop.setpoint.change_times()
    bounds = [*changes, scenario.duration_s]
    steps = [
        step_metrics(result.t, result.true[LT_102], t0, loop.setpoint.value_at(t0), t_end=t1)
        for t0, t1 in itertools.pairwise(bounds)
    ]
    return loop, result, steps


def summarize(steps) -> dict:
    settle = [s.settling_time_s for s in steps]
    return {
        "max_sobrepaso_pct": max(s.overshoot_pct for s in steps),
        "max_error_estacionario_pct": max(s.steady_state_error_pct for s in steps),
        "max_establecimiento_s": None if None in settle else max(settle),
        "iae_total": sum(s.iae for s in steps),
        "cumple_rf07": all(
            s.overshoot_pct < OVERSHOOT_MAX and s.steady_state_error_pct < SSE_MAX for s in steps
        ),
    }


def sweep(config: dict, scenario, top: int = 15) -> None:
    """Barrido de (Kp, Ki, Kd) en el escenario dado. Ordena por cumplimiento de RF-07 con margen
    (sobrepaso < 10 %), luego por IAE + penalización del ruido en la bomba."""
    rows = []
    grid = itertools.product(
        [1.5, 2.0, 2.5, 3.0, 4.0], [0.01, 0.015, 0.02, 0.03, 0.04], [0.0, 30.0, 60.0, 120.0]
    )
    for kp, ki, kd in grid:
        _, result, steps = evaluate(config, scenario, {"kp": kp, "ki": ki, "kd": kd}, "rk4", None)
        s = summarize(steps)
        u = result.command[:: round(result.meta["ts_s"] / result.meta["dt_s"])]
        s["ruido_bomba_pct"] = float(np.std(np.diff(u)))
        s["margen"] = s["cumple_rf07"] and s["max_sobrepaso_pct"] < 10.0
        rows.append((kp, ki, kd, s))
    rows.sort(key=lambda r: (not r[3]["margen"], r[3]["iae_total"] * (1 + r[3]["ruido_bomba_pct"])))
    print(
        f"{'Kp':>4} {'Ki':>6} {'Kd':>5} {'sobrepaso%':>10} {'e_ss%':>6} {'t_est[s]':>8} "
        f"{'IAE':>6} {'ruido_u%':>8}  RF-07"
    )
    for kp, ki, kd, s in rows[:top]:
        ts = s["max_establecimiento_s"]
        ts_txt = "—" if ts is None else str(round(ts))
        print(
            f"{kp:4.1f} {ki:6.3f} {kd:5.0f} {s['max_sobrepaso_pct']:10.1f} "
            f"{s['max_error_estacionario_pct']:6.2f} {ts_txt:>8} {s['iae_total']:6.0f} "
            f"{s['ruido_bomba_pct']:8.2f}  {'sí' if s['cumple_rf07'] else 'no'}"
        )


def plot(result, scenario, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, dpi=150)
    ax1.plot(result.t, result.measured[LT_102], color="#9ec5e8", lw=0.6, label="LT-102 medido")
    ax1.plot(result.t, result.true[LT_102], color="#2E6DA4", lw=1.4, label="h2 real")
    ax1.plot(result.t, result.true[LT_101], color="#3C8D40", lw=1.2, label="h1 real")
    ax1.plot(result.t, result.setpoint, "k--", lw=1.0, label="Consigna")
    ax1.set_ylabel("Nivel [cm]")
    ax1.legend(loc="upper right", ncol=4, fontsize=8)
    ax2.plot(result.t, result.true[P_101], color="#B7791F", lw=1.0)
    ax2.set_ylabel("Bomba P-101 [%]")
    ax2.set_xlabel("Tiempo [s]")
    for d in scenario.disturbances:
        if d.get("type") == "process_noise":
            continue  # el ruido de proceso dura toda la corrida; no se sombrea
        for ax in (ax1, ax2):
            ax.axvspan(d["t_s"], d["t_s"] + d["duration_s"], color="#C0392B", alpha=0.08)
    ax1.set_title(
        f"Lazo cerrado offline — escenario {scenario.name} "
        "(bandas rojas: perturbaciones legítimas)",
        fontsize=10,
    )
    for ax in (ax1, ax2):
        ax.grid(alpha=0.3)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibración del lazo de nivel (Fase 2).")
    parser.add_argument("--config", default=str(paths.DEFAULT_CONFIG))
    parser.add_argument("--escenario", default=str(paths.SCENARIOS_DIR / "normal.yaml"))
    parser.add_argument("--kp", type=float)
    parser.add_argument("--ki", type=float)
    parser.add_argument("--kd", type=float)
    parser.add_argument("--integrador", choices=["solve_ivp", "rk4"])
    parser.add_argument("--semilla", type=int)
    parser.add_argument("--barrido", action="store_true")
    args = parser.parse_args(argv)

    config = load_yaml(args.config)
    scenario = load_scenario(args.escenario)
    if args.barrido:
        sweep(config, scenario)
        return 0

    overrides = {
        k: v for k, v in (("kp", args.kp), ("ki", args.ki), ("kd", args.kd)) if v is not None
    }
    loop, result, steps = evaluate(config, scenario, overrides, args.integrador, args.semilla)
    p = loop.pid.params
    dt_ms = result.meta["dt_s"] * 1000
    compute_ms = result.step_compute_s * 1000
    print(
        f"Escenario {scenario.name} · {scenario.duration_s:.0f} s · integrador "
        f"{result.meta['integrator']} · Kp={p.kp} Ki={p.ki} Kd={p.kd} Ts={p.ts_s}s"
    )
    print(
        f"{'t_escalón':>9} {'de→a [cm]':>13} {'sobrepaso%':>11} {'e_ss%':>7} "
        f"{'t_est[s]':>9} {'t_sub[s]':>9}"
    )
    for s in steps:
        print(
            f"{s.t_step:9.0f} {s.initial:6.1f}→{s.setpoint:<5.1f} {s.overshoot_pct:11.2f} "
            f"{s.steady_state_error_pct:7.2f} {s.settling_time_s!s:>9.6} {s.rise_time_s!s:>9.6}"
        )
    summary = summarize(steps)
    if scenario.disturbances:
        # RF-07 se define en operación nominal; con perturbaciones los indicadores mezclan la
        # respuesta a la consigna con la respuesta a la perturbación (se reportan, no se juzgan).
        summary["cumple_rf07"] = None
    p99 = float(np.percentile(compute_ms, 99))
    summary["computo_paso_ms"] = {
        "media": float(compute_ms.mean()),
        "p99": p99,
        "limite_rnf01": 0.1 * dt_ms,
        "cumple_rnf01": p99 < 0.1 * dt_ms,
    }
    summary["rango_bomba_pct"] = [float(result.true[P_101].min()), float(result.true[P_101].max())]
    summary["rango_h1_cm"] = [float(result.true[LT_101].min()), float(result.true[LT_101].max())]
    verdict = {
        True: "cumple",
        False: "NO cumple",
        None: "no aplica (escenario con perturbaciones)",
    }[summary["cumple_rf07"]]
    print(
        f"RF-07 {verdict} · cómputo por paso "
        f"media {compute_ms.mean():.3f} ms, p99 {p99:.3f} ms (RNF-01 < {0.1 * dt_ms:.0f} ms)"
    )

    out = paths.RESULTS_DIR / "fase2"
    plot(result, scenario, out / f"lazo_{scenario.name}.png")
    report = {
        "escenario": scenario.name,
        "ganancias": {"kp": p.kp, "ki": p.ki, "kd": p.kd},
        "escalones": [s.as_dict() for s in steps],
        "resumen": summary,
    }
    (out / f"lazo_{scenario.name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Figura y resumen en {out}")
    return 1 if summary["cumple_rf07"] is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
