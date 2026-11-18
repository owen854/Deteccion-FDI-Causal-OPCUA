"""Actuador: bomba P-101 con saturación y dinámica de primer orden opcional (RF-03).

``q_in = k_p · u_ef``, con el comando ``u`` saturado en [min_pct, max_pct] y
``τ · du_ef/dt = u − u_ef`` (discretización exacta para entrada constante) si τ > 0.

Implementado en la Fase 2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdisim.common.config import ConfigError


@dataclass(frozen=True, slots=True)
class PumpParams:
    gain_cm3_s_per_pct: float
    time_constant_s: float = 0.0
    min_pct: float = 0.0
    max_pct: float = 100.0

    def __post_init__(self) -> None:
        if self.gain_cm3_s_per_pct <= 0:
            raise ConfigError(
                f"plant.pump.gain_cm3_s_per_pct: debe ser positiva ({self.gain_cm3_s_per_pct})"
            )
        if self.time_constant_s < 0:
            raise ConfigError(f"plant.pump.time_constant_s: debe ser ≥ 0 ({self.time_constant_s})")
        if not self.min_pct < self.max_pct:
            raise ConfigError("plant.pump: min_pct debe ser menor que max_pct")

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> PumpParams:
        return cls(
            float(cfg["gain_cm3_s_per_pct"]),
            float(cfg.get("time_constant_s", 0.0)),
            float(cfg.get("min_pct", 0.0)),
            float(cfg.get("max_pct", 100.0)),
        )


class Pump:
    def __init__(self, params: PumpParams) -> None:
        self.params = params
        self.command_pct = params.min_pct  # último comando aplicado (saturado)
        self.effective_pct = params.min_pct  # salida tras la dinámica del actuador

    def saturate(self, command_pct: float) -> float:
        return min(max(command_pct, self.params.min_pct), self.params.max_pct)

    def reset(self, command_pct: float) -> None:
        self.command_pct = self.effective_pct = self.saturate(command_pct)

    def apply(self, command_pct: float, dt: float) -> float:
        """Aplica el comando ``u`` durante ``dt`` y devuelve el caudal ``q_in`` [cm³/s]."""
        self.command_pct = self.saturate(command_pct)
        tau = self.params.time_constant_s
        if tau > 0:
            alpha = 1.0 - math.exp(-dt / tau)
            self.effective_pct += alpha * (self.command_pct - self.effective_pct)
        else:
            self.effective_pct = self.command_pct
        return self.params.gain_cm3_s_per_pct * self.effective_pct

    def command_for_flow(self, q_cm3_s: float) -> float:
        """Comando en estado estacionario que produce el caudal ``q`` (saturado)."""
        return self.saturate(q_cm3_s / self.params.gain_cm3_s_per_pct)
