"""Ataque de repetición (replay) (RF-19).

Fase de grabación: ``observe`` almacena los valores legítimos de la ventana
``[tₛ − record_s, tₛ)``. Fase de reproducción: ``falsify`` devuelve la muestra grabada en la
posición ``(t − tₛ) mod record_s``, de modo que la ventana se repite en bucle.
La grabación no altera los datos en tránsito.

Parámetros del escenario: ``record_s``.
Fase de implementación: Fase 4.
"""

from __future__ import annotations

from fdisim.attacks.base import AttackStrategy, register_attack
from fdisim.common.types import AttackType


@register_attack(AttackType.REPLAY)
class ReplayAttack(AttackStrategy):
    def observe(self, tag: str, value: float, t: float) -> None:
        raise NotImplementedError("Fase 4 — RF-19: grabación del replay")

    def falsify(self, tag: str, value: float, t: float) -> float:
        raise NotImplementedError("Fase 4 — RF-19: reproducción del replay")
