"""Motor de inyección FDI instalado en el gateway comprometido (RF-16, RF-21, RF-24).

Para cada valor que llega de la planta: ``observe`` en todas las estrategias de esa variable,
aplicar las estrategias activas (en orden, lo que permite ataques coordinados), luego el filtro
de sigilo, y devolver el valor a publicar. Conserva el tipo de dato, el StatusCode Good y las
marcas de tiempo (las pone el gateway), de modo que la falsificación es válida en el protocolo
aunque el canal sea SignAndEncrypt. Fuera de la ventana de ataque el valor pasa intacto.

Dos sentidos de inyección:

- ``process``: mediciones que viajan planta → clientes (LT-101, LT-102, FT-101);
- ``process_command``: órdenes que viajan clientes → planta (P-101, consigna; RF-24). El
  gateway sigue mostrando a los clientes la orden que ellos escribieron, de modo que la
  manipulación del actuador queda oculta.

El inyector guarda un historial reciente de cada variable para que un replay armado en
caliente (RF-23) tenga grabación desde el primer instante, y publica los ``AttackEvent`` de
inicio y fin por el plano de experimento (RF-21).

En modo offline, la misma clase se aplica entre la planta simulada y los detectores (RF-38).

Implementado en la Fase 4.
"""

from __future__ import annotations

import dataclasses
from collections import deque

from fdisim.attacks.scheduler import AttackScheduler, ScheduledAttack
from fdisim.common.bus import ExperimentBus
from fdisim.common.types import AttackEvent, AttackSpec


class FdiInjector:
    def __init__(
        self,
        scheduler: AttackScheduler,
        bus: ExperimentBus | None = None,
        history_s: float = 600.0,
    ) -> None:
        self.scheduler = scheduler
        self.bus = bus
        self.history_s = history_s
        self.falsified = 0
        self._history: dict[str, deque[tuple[float, float]]] = {}
        self._last_t = 0.0
        self.event_log: list[AttackEvent] = []

    # ------------------------------------------------------------------ inyección
    def process(self, tag: str, value: float, sim_time: float) -> float:
        """Devuelve el valor que publicará el gateway (legítimo o falsificado)."""
        self._advance(sim_time)
        self._remember(tag, value, sim_time)
        scheduled = self.scheduler.strategies_for(tag)
        for attack in scheduled:
            attack.strategy.observe(tag, value, sim_time)
        out = value
        active = [a for a in scheduled if a.is_active(sim_time)]
        for attack in active:
            out = attack.strategy.falsify(tag, out, sim_time)
            out = attack.stealth.apply(tag, out, sim_time, original=value, t_end=attack.end)
        for attack in scheduled:
            attack.stealth.track(tag, out, value, sim_time)
        if active:
            self.falsified += 1
        return out

    def process_command(self, tag: str, value: float, sim_time: float) -> float:
        """Orden escrita por un cliente → valor que el gateway entrega a la planta (RF-24)."""
        return self.process(tag, value, sim_time)

    def is_attacking(self, tag: str, sim_time: float) -> bool:
        return bool(self.scheduler.active_for(tag, sim_time))

    # ------------------------------------------------------------------ control en caliente
    def arm(self, spec: AttackSpec, start_now: bool = False) -> AttackSpec:
        """Arma un ataque; con ``start_now`` empieza en el tiempo simulado actual (RF-23)."""
        if start_now:
            spec = dataclasses.replace(spec, start_s=self._last_t)
        scheduled = self.scheduler.arm(spec)
        self._preload(scheduled)
        self._advance(self._last_t)
        return spec

    def disarm(self, attack_id: str) -> None:
        self.scheduler.disarm(attack_id, self._last_t)
        self._advance(self._last_t)

    def events(self) -> list[AttackEvent]:
        return self.scheduler.events()

    # ------------------------------------------------------------------ utilidades
    def _advance(self, sim_time: float) -> None:
        self._last_t = max(self._last_t, sim_time)
        for event in self.scheduler.transitions(self._last_t):
            self.event_log.append(event)
            if self.bus is not None:
                self.bus.publish_attack_event(event)

    def _remember(self, tag: str, value: float, t: float) -> None:
        buf = self._history.setdefault(tag, deque())
        buf.append((t, value))
        while buf and buf[0][0] < t - self.history_s:
            buf.popleft()

    def _preload(self, scheduled: ScheduledAttack) -> None:
        for tag in scheduled.spec.targets:
            for t, value in self._history.get(tag, ()):
                scheduled.strategy.observe(tag, value, t)
                scheduled.stealth.track(tag, value, value, t)
