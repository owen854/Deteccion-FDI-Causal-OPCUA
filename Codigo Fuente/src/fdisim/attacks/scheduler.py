"""Programador de ataques y etiquetado (RF-20, RF-21, RF-23).

Mantiene las estrategias del escenario (y las armadas en caliente desde la HMI), decide cuáles
están activas en cada instante simulado y produce los ``AttackEvent`` de inicio y fin, que son
las etiquetas de evaluación. Un ataque puede desarmarse antes de su fin programado; desde ese
instante deja de estar activo y su evento queda cerrado en ese tiempo.

Implementado en la Fase 4.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdisim.attacks.base import AttackStrategy, create_attack
from fdisim.attacks.stealth import StealthFilter
from fdisim.common.types import AttackEvent, AttackSpec


@dataclass(slots=True)
class ScheduledAttack:
    strategy: AttackStrategy
    stealth: StealthFilter
    disarmed_at: float | None = None
    started: bool = False
    finished: bool = False

    @property
    def spec(self) -> AttackSpec:
        return self.strategy.spec

    @property
    def end(self) -> float:
        end = self.spec.end_s
        return end if self.disarmed_at is None else min(end, self.disarmed_at)

    def is_active(self, t: float) -> bool:
        return self.spec.start_s <= t < self.end


class AttackScheduler:
    def __init__(self, specs: list[AttackSpec] | tuple[AttackSpec, ...] = ()) -> None:
        self.specs: list[AttackSpec] = []
        self._attacks: dict[str, ScheduledAttack] = {}
        for spec in specs:
            self.arm(spec)

    # ------------------------------------------------------------------ programación
    @property
    def attacks(self) -> list[ScheduledAttack]:
        return list(self._attacks.values())

    def get(self, attack_id: str) -> ScheduledAttack:
        return self._attacks[attack_id]

    def arm(self, spec: AttackSpec) -> ScheduledAttack:
        """Arma un ataque (del escenario o en caliente, RF-23)."""
        if spec.attack_id in self._attacks:
            raise ValueError(f"Ya existe un ataque con id {spec.attack_id}")
        scheduled = ScheduledAttack(create_attack(spec), StealthFilter(spec.stealth))
        self._attacks[spec.attack_id] = scheduled
        self.specs.append(spec)
        return scheduled

    def disarm(self, attack_id: str, t: float) -> None:
        """Desarma un ataque en el instante ``t`` (no tiene efecto si ya terminó)."""
        scheduled = self._attacks[attack_id]
        if scheduled.disarmed_at is None or t < scheduled.disarmed_at:
            scheduled.disarmed_at = max(t, scheduled.spec.start_s)

    def strategies_for(self, tag: str) -> list[ScheduledAttack]:
        return [a for a in self._attacks.values() if a.strategy.applies_to(tag)]

    def active_for(self, tag: str, t: float) -> list[AttackStrategy]:
        return [a.strategy for a in self.strategies_for(tag) if a.is_active(t)]

    # ------------------------------------------------------------------ etiquetas
    def label_at(self, t: float) -> int:
        """Etiqueta por muestra: 1 si algún ataque está activo, 0 si no (RF-21)."""
        return int(any(a.is_active(t) for a in self._attacks.values()))

    def active_ids(self, t: float) -> list[str]:
        return [a.spec.attack_id for a in self._attacks.values() if a.is_active(t)]

    def transitions(self, t: float) -> list[AttackEvent]:
        """Eventos de inicio o fin ocurridos hasta ``t`` que aún no se habían reportado."""
        out = []
        for a in self._attacks.values():
            if not a.started and t >= a.spec.start_s and t < a.end:
                a.started = True
                out.append(self._event(a, closed=False))
            if a.started and not a.finished and t >= a.end:
                a.finished = True
                out.append(self._event(a, closed=True))
        return out

    def events(self) -> list[AttackEvent]:
        """Intervalos de ataque efectivos (los que llegaron a empezar)."""
        return [self._event(a, closed=a.finished) for a in self._attacks.values() if a.started]

    @staticmethod
    def _event(a: ScheduledAttack, closed: bool) -> AttackEvent:
        spec = a.spec
        return AttackEvent(
            spec.attack_id,
            spec.type,
            spec.targets,
            spec.start_s,
            a.end if closed else None,
            dict(spec.params),
        )
