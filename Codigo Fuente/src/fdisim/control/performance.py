"""Indicadores de desempeño del lazo de control (criterio de aceptación de RF-07).

Para un cambio de consigna ``y0 → SP`` en ``t_step``, sobre la señal **real** (sin ruido) del
nivel controlado:

- **Sobrepaso** [% del escalón].
- **Error en estado estacionario** [% de la consigna], promedio del último 10 % de la ventana.
- **Tiempo de establecimiento** [s] dentro de una banda de ±2 % del escalón.
- **Tiempo de subida** [s] del 10 % al 90 % del escalón.
- **IAE** [cm·s], integral del error absoluto.

Implementado en la Fase 2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class StepMetrics:
    t_step: float
    initial: float
    setpoint: float
    overshoot_pct: float
    steady_state_error_pct: float
    settling_time_s: float | None
    rise_time_s: float | None
    iae: float

    def as_dict(self) -> dict:
        return asdict(self)


def step_metrics(
    t: np.ndarray,
    y: np.ndarray,
    t_step: float,
    setpoint: float,
    t_end: float | None = None,
    band: float = 0.02,
) -> StepMetrics:
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (t >= t_step) & (t < (t_end if t_end is not None else np.inf))
    tw, yw = t[mask], y[mask]
    if len(tw) < 10:
        raise ValueError("Ventana demasiado corta para evaluar el escalón")
    before = y[t < t_step]
    y0 = float(before[-1]) if len(before) else float(yw[0])
    delta = setpoint - y0
    direction = 1.0 if delta >= 0 else -1.0
    size = abs(delta) if abs(delta) > 1e-9 else 1.0

    peak = float(np.max(direction * (yw - setpoint)))
    overshoot = max(0.0, peak) / size * 100.0
    tail = yw[int(0.9 * len(yw)) :]
    sse = abs(float(np.mean(tail)) - setpoint) / max(abs(setpoint), 1e-9) * 100.0

    outside = np.nonzero(np.abs(yw - setpoint) > band * size)[0]
    if len(outside) == 0:
        settling: float | None = 0.0
    elif outside[-1] == len(yw) - 1:
        settling = None  # no se establece dentro de la ventana
    else:
        settling = float(tw[outside[-1] + 1] - t_step)

    progress = direction * (yw - y0) / size
    i10 = np.nonzero(progress >= 0.1)[0]
    i90 = np.nonzero(progress >= 0.9)[0]
    rise = float(tw[i90[0]] - tw[i10[0]]) if len(i10) and len(i90) else None
    iae = float(np.trapezoid(np.abs(setpoint - yw), tw))
    return StepMetrics(t_step, y0, setpoint, overshoot, sse, settling, rise, iae)
