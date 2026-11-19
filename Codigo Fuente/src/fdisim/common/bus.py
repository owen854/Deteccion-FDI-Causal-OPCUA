"""Plano de experimento: canal local y confiable fuera de banda (RF-06, RF-21, RF-54).

Transporta la verdad de terreno, las etiquetas de ataque, las estadísticas de los componentes
y los comandos de control del experimento (iniciar, detener, armar ataque). **Nunca**
transporta las variables que debe analizar el detector: esas viajan solo por OPC UA (plano de
datos), para que el detector vea exactamente lo que vería un sistema de supervisión real.

Implementación: el orquestador crea un ``ExperimentHub`` con una cola de eventos
(componentes → orquestador) y una cola de comandos por componente. Las colas son de
``multiprocessing`` cuando cada componente es un proceso, o de ``queue`` en pruebas dentro de
un mismo proceso. Un ``ExperimentBus`` sin colas («desconectado») ignora las publicaciones;
sirve para ejecutar un componente aislado, p. ej. el servidor de planta para UaExpert.

Implementado en la Fase 3.
"""

from __future__ import annotations

import multiprocessing
import queue
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fdisim.common.types import AttackEvent, AttackSpec, GroundTruthRecord


class CommandType(StrEnum):
    START = "start"
    STOP = "stop"
    SET_SETPOINT = "set_setpoint"  # RF-09
    ARM_ATTACK = "arm_attack"  # RF-23
    DISARM_ATTACK = "disarm_attack"


@dataclass(frozen=True, slots=True)
class Command:
    type: CommandType
    payload: dict[str, Any] = field(default_factory=dict)


class EventType(StrEnum):
    READY = "ready"  # el componente arrancó y está conectado
    GROUND_TRUTH = "ground_truth"  # RF-06
    ATTACK = "attack"  # RF-21
    FINISHED = "finished"  # la planta completó la duración del escenario
    STATS = "stats"  # estadísticas finales del componente
    ERROR = "error"  # fallo irrecuperable


@dataclass(frozen=True, slots=True)
class Event:
    source: str
    type: EventType
    payload: Any = None
    wall_ts: float = field(default_factory=time.time)


class ExperimentBus:
    """Punto de acceso al plano de experimento para un componente."""

    def __init__(
        self,
        component: str,
        events: Any | None = None,
        commands: Mapping[str, Any] | None = None,
    ) -> None:
        self.component = component
        self._events = events
        self._commands = dict(commands or {})

    @property
    def connected(self) -> bool:
        return self._events is not None

    def publish(self, type_: EventType, payload: Any = None) -> None:
        if self._events is not None:
            self._events.put(Event(self.component, type_, payload))

    def publish_ground_truth(self, record: GroundTruthRecord) -> None:
        self.publish(EventType.GROUND_TRUTH, record)

    def publish_attack_event(self, event: AttackEvent) -> None:
        self.publish(EventType.ATTACK, event)

    def send_command(self, target: str, command: Command) -> None:
        if target not in self._commands:
            raise KeyError(f"Componente sin cola de comandos: {target}")
        self._commands[target].put(command)

    def poll_commands(self) -> list[Command]:
        """Comandos pendientes para este componente (no bloqueante)."""
        own = self._commands.get(self.component)
        out: list[Command] = []
        if own is None:
            return out
        while True:
            try:
                out.append(own.get_nowait())
            except queue.Empty:
                return out

    def arm_attack(self, spec: AttackSpec) -> None:
        """Atajo para RF-23: ordena al gateway armar un ataque."""
        self.send_command("gateway", Command(CommandType.ARM_ATTACK, {"spec": spec}))


class ExperimentHub:
    """Colas del plano de experimento; las crea y las lee el orquestador."""

    def __init__(self, components: Iterable[str], multiprocess: bool = True) -> None:
        if multiprocess:
            ctx = multiprocessing.get_context("spawn")
            self.events: Any = ctx.Queue()
            self.commands: dict[str, Any] = {c: ctx.Queue() for c in components}
        else:
            self.events = queue.Queue()
            self.commands = {c: queue.Queue() for c in components}
        self.multiprocess = multiprocess

    def bus_for(self, component: str) -> ExperimentBus:
        return ExperimentBus(component, self.events, self.commands)

    def send_command(self, target: str, command: Command) -> None:
        self.commands[target].put(command)

    def drain(self, timeout_s: float = 0.0) -> list[Event]:
        """Eventos pendientes; espera hasta ``timeout_s`` por el primero."""
        out: list[Event] = []
        try:
            out.append(
                self.events.get(timeout=timeout_s) if timeout_s > 0 else self.events.get_nowait()
            )
        except queue.Empty:
            return out
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def close(self) -> None:
        if not self.multiprocess:
            return
        for q in (self.events, *self.commands.values()):
            q.close()
            q.cancel_join_thread()
