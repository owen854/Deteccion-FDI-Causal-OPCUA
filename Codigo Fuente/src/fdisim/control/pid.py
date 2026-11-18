"""Controlador PID discreto con anti-windup y filtro derivativo (RF-07).

Forma paralela, periodo de muestreo ``ts_s``::

    u(k) = sat[ Kp·e(k) + Ki·Σe·Ts + Kd·D_f(k) ],   e = SP − y

Anti-windup por ``clamping`` (congela la integral al saturar) o ``back_calculation``.
La sintonía inicial se hace en la Fase 2 (IMC/λ o Ziegler-Nichols con ajuste fino).

Fase de implementación: Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PIDParams:
    kp: float
    ki: float
    kd: float
    ts_s: float
    out_min: float = 0.0
    out_max: float = 100.0
    derivative_filter_n: float = 10.0
    anti_windup: str = "clamping"  # clamping | back_calculation


class PIDController:
    def __init__(self, params: PIDParams) -> None:
        self.params = params

    def reset(self) -> None:
        """Reinicia la integral y la memoria derivativa."""
        raise NotImplementedError("Fase 2 — RF-07: PID discreto")

    def update(self, setpoint: float, measurement: float) -> float:
        """Calcula la acción de control para un periodo ``ts_s`` (siempre en [out_min, out_max])."""
        raise NotImplementedError("Fase 2 — RF-07: PID discreto")
