"""Ataque de sesgo: ``yₐ(t) = y(t) + b`` (RF-17).

Parámetros del escenario: ``bias`` (b, en unidades de la variable).
Fase de implementación: Fase 4.
"""

from __future__ import annotations

from fdisim.attacks.base import AttackStrategy, register_attack
from fdisim.common.types import AttackType


@register_attack(AttackType.BIAS)
class BiasAttack(AttackStrategy):
    def falsify(self, tag: str, value: float, t: float) -> float:
        raise NotImplementedError("Fase 4 — RF-17: ataque de sesgo")
