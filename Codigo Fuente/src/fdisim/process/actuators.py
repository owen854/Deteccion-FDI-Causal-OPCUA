"""Actuador: bomba P-101 con saturación y dinámica de primer orden opcional (RF-03).

``q_in = k_p · u_efectivo``, con ``u`` saturado en [min_pct, max_pct] y
``τ · du_ef/dt = u − u_ef`` si ``time_constant_s > 0``.

Fase de implementación: Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PumpParams:
    gain_cm3_s_per_pct: float
    time_constant_s: float = 0.0
    min_pct: float = 0.0
    max_pct: float = 100.0


class Pump:
    def __init__(self, params: PumpParams) -> None:
        self.params = params

    def apply(self, command_pct: float, dt: float) -> float:
        """Aplica el comando ``u`` durante ``dt`` y devuelve el caudal ``q_in`` [cm³/s]."""
        raise NotImplementedError("Fase 2 — RF-03: saturación y dinámica de la bomba")
