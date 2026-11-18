"""Plano de experimento: canal local y confiable fuera de banda (RF-06, RF-21).

Transporta la verdad de terreno, las etiquetas de ataque y los comandos de control del
experimento (iniciar, detener, armar ataque). **Nunca** transporta las variables que debe
analizar el detector: esas viajan solo por OPC UA (plano de datos), para que el detector vea
exactamente lo que vería un sistema de supervisión real.

Implementación prevista: colas de ``multiprocessing`` creadas por el orquestador, una de
eventos (componentes → orquestador) y una de comandos por componente.

Fase de implementación: Fase 3.
"""

from __future__ import annotations

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


class ExperimentBus:
    """Punto de acceso al plano de experimento para un componente."""

    def __init__(self, component: str) -> None:
        self.component = component

    def publish_ground_truth(self, record: GroundTruthRecord) -> None:
        raise NotImplementedError("Fase 3 — RF-06: verdad de terreno fuera de banda")

    def publish_attack_event(self, event: AttackEvent) -> None:
        raise NotImplementedError("Fase 4 — RF-21: etiquetado de ataques")

    def send_command(self, target: str, command: Command) -> None:
        raise NotImplementedError("Fase 3 — RF-54: control de componentes")

    def poll_commands(self) -> list[Command]:
        """Comandos pendientes para este componente (no bloqueante)."""
        raise NotImplementedError("Fase 3 — RF-54: control de componentes")

    def arm_attack(self, spec: AttackSpec) -> None:
        """Atajo para RF-23: ordena al gateway armar un ataque."""
        self.send_command("gateway", Command(CommandType.ARM_ATTACK, {"spec": spec}))
