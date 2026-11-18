"""Controlador PID discreto con anti-windup y filtro derivativo (RF-07).

Forma paralela, periodo de muestreo ``Ts``::

    e(k)  = SP(k) − y(k)
    P(k)  = Kp·e(k)
    I(k)  = I(k−1) + Ki·Ts·e(k)                       (con anti-windup)
    D(k)  = Tf/(Tf+Ts)·D(k−1) − Kd/(Tf+Ts)·(y(k) − y(k−1)),   Tf = (Kd/Kp)/N
    u(k)  = sat[ P(k) + I(k) + D(k) ]

La derivada actúa sobre la medición (no sobre el error) para evitar picos ante cambios de
consigna, y se filtra con constante ``Tf`` para no amplificar el ruido del sensor.

Anti-windup:
- ``clamping``: si la salida está saturada y el error empuja más hacia la saturación, se
  descarta el incremento integral de ese periodo.
- ``back_calculation``: la integral se corrige con ``(u − u_sin_saturar)·Ts/Tt``.

Implementado en la Fase 2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdisim.common.config import ConfigError

ANTI_WINDUP = ("clamping", "back_calculation")


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

    def __post_init__(self) -> None:
        if min(self.kp, self.ki, self.kd) < 0:
            raise ConfigError("control: las ganancias kp, ki y kd deben ser ≥ 0")
        if self.ts_s <= 0:
            raise ConfigError(f"control.ts_s: debe ser positivo ({self.ts_s})")
        if not self.out_min < self.out_max:
            raise ConfigError("control: out_min debe ser menor que out_max")
        if self.derivative_filter_n <= 0:
            raise ConfigError("control.derivative_filter_n: debe ser positivo")
        if self.anti_windup not in ANTI_WINDUP:
            raise ConfigError(f"control.anti_windup: use {ANTI_WINDUP} (valor: {self.anti_windup})")

    @classmethod
    def from_config(cls, control: Mapping[str, Any]) -> PIDParams:
        return cls(
            kp=float(control["kp"]),
            ki=float(control.get("ki", 0.0)),
            kd=float(control.get("kd", 0.0)),
            ts_s=float(control["ts_s"]),
            out_min=float(control.get("out_min", 0.0)),
            out_max=float(control.get("out_max", 100.0)),
            derivative_filter_n=float(control.get("derivative_filter_n", 10.0)),
            anti_windup=str(control.get("anti_windup", "clamping")),
        )


class PIDController:
    def __init__(self, params: PIDParams) -> None:
        self.params = params
        self.reset()

    def reset(self, initial_output: float = 0.0) -> None:
        """Reinicia la memoria. ``initial_output`` precarga la integral para un arranque sin
        saltos (p. ej. con la bomba ya en el punto de equilibrio)."""
        p = self.params
        self.integral = min(max(initial_output, p.out_min), p.out_max)
        self.derivative = 0.0
        self._last_measurement: float | None = None
        self.last_error = 0.0
        self.last_output = self.integral
        self.last_unsaturated = self.integral

    def update(self, setpoint: float, measurement: float) -> float:
        """Calcula la acción de control para un periodo ``Ts`` (siempre en [out_min, out_max])."""
        p = self.params
        ts = p.ts_s
        error = setpoint - measurement
        proportional = p.kp * error

        if p.kd > 0 and self._last_measurement is not None:
            tf = (p.kd / p.kp) / p.derivative_filter_n if p.kp > 0 else ts
            self.derivative = (tf / (tf + ts)) * self.derivative - (p.kd / (tf + ts)) * (
                measurement - self._last_measurement
            )
        self._last_measurement = measurement

        increment = p.ki * ts * error
        unsaturated = proportional + self.integral + increment + self.derivative
        output = min(max(unsaturated, p.out_min), p.out_max)

        if p.anti_windup == "clamping":
            pushing_high = unsaturated > p.out_max and error > 0
            pushing_low = unsaturated < p.out_min and error < 0
            if not (pushing_high or pushing_low):
                self.integral += increment
        else:  # back_calculation
            tt = self._tracking_time()
            self.integral += increment + (output - unsaturated) * ts / tt

        self.last_error = error
        self.last_unsaturated = unsaturated
        self.last_output = output
        return output

    def _tracking_time(self) -> float:
        p = self.params
        if p.ki <= 0:
            return p.ts_s
        ti = p.kp / p.ki if p.kp > 0 else 1.0 / p.ki
        td = p.kd / p.kp if p.kp > 0 else 0.0
        return max(math.sqrt(ti * td) if td > 0 else ti, p.ts_s)
