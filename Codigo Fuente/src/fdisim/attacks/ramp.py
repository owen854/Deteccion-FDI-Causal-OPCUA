"""Ataque de rampa: ``yₐ(t) = y(t) + r·(t − tₛ)``, con ``|r·(t − tₛ)| ≤ Δ_max`` (RF-18).

Parámetros del escenario: ``slope_per_s`` (r) y ``max_deviation`` (Δ_max, opcional).
Fase de implementación: Fase 4.
"""

from __future__ import annotations

from fdisim.attacks.base import AttackStrategy, register_attack
from fdisim.common.types import AttackType


@register_attack(AttackType.RAMP)
class RampAttack(AttackStrategy):
    def falsify(self, tag: str, value: float, t: float) -> float:
        raise NotImplementedError("Fase 4 — RF-18: ataque de rampa")
