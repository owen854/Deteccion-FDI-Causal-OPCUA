"""Ataque de sesgo: ``yₐ(t) = y(t) + b`` (RF-17).

Parámetros del escenario: ``bias`` (b, en unidades de la variable).
Implementado en la Fase 4.
"""

from __future__ import annotations

from fdisim.attacks.base import AttackStrategy, register_attack
from fdisim.common.types import AttackType


@register_attack(AttackType.BIAS)
class BiasAttack(AttackStrategy):
    def __init__(self, spec) -> None:  # noqa: ANN001
        super().__init__(spec)
        if "bias" not in spec.params:
            raise ValueError(f"{spec.attack_id}: el sesgo requiere el parámetro 'bias'")
        self.bias = float(spec.params["bias"])

    def falsify(self, tag: str, value: float, t: float) -> float:
        return value + self.bias
