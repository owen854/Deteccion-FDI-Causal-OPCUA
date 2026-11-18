"""Programador de ataques y etiquetado (RF-20, RF-21, RF-23).

Mantiene las estrategias del escenario (y las armadas desde la HMI), decide cuáles están
activas en cada instante y emite ``AttackEvent`` de inicio y fin por el plano de experimento.

Fase de implementación: Fase 4.
"""

from __future__ import annotations

from fdisim.attacks.base import AttackStrategy
from fdisim.common.types import AttackEvent, AttackSpec


class AttackScheduler:
    def __init__(self, specs: list[AttackSpec]) -> None:
        self.specs = specs

    def active_for(self, tag: str, t: float) -> list[AttackStrategy]:
        raise NotImplementedError("Fase 4 — RF-20: programación de ataques")

    def arm(self, spec: AttackSpec) -> None:
        """Arma un ataque en caliente (RF-23)."""
        raise NotImplementedError("Fase 4 — RF-23: activación interactiva")

    def label_at(self, t: float) -> int:
        """Etiqueta por muestra: 1 si algún ataque está activo, 0 si no (RF-21)."""
        raise NotImplementedError("Fase 4 — RF-21: etiquetado")

    def events(self) -> list[AttackEvent]:
        raise NotImplementedError("Fase 4 — RF-21: eventos de ataque")
