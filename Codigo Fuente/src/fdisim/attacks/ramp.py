"""Ataque de rampa: ``yₐ(t) = y(t) + r·(t − tₛ)``, con ``|r·(t − tₛ)| ≤ Δ_max`` (RF-18).

Parámetros del escenario: ``slope_per_s`` (r) y ``max_deviation`` (Δ_max, opcional).
Implementado en la Fase 4.
"""

from __future__ import annotations

import math

from fdisim.attacks.base import AttackStrategy, register_attack
from fdisim.common.types import AttackType


@register_attack(AttackType.RAMP)
class RampAttack(AttackStrategy):
    def __init__(self, spec) -> None:  # noqa: ANN001
        super().__init__(spec)
        if "slope_per_s" not in spec.params:
            raise ValueError(f"{spec.attack_id}: la rampa requiere el parámetro 'slope_per_s'")
        self.slope = float(spec.params["slope_per_s"])
        limit = spec.params.get("max_deviation")
        self.max_deviation = abs(float(limit)) if limit is not None else math.inf

    def deviation(self, t: float) -> float:
        raw = self.slope * max(0.0, t - self.spec.start_s)
        return math.copysign(min(abs(raw), self.max_deviation), raw)

    def falsify(self, tag: str, value: float, t: float) -> float:
        return value + self.deviation(t)
