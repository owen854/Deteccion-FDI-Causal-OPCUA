"""Lanzador de componentes como procesos independientes (RF-54).

Orden de arranque: servidor de planta (4840) → gateway (4841) → controlador → monitor →
(HMI). Cada componente es un ``multiprocessing.Process`` con su cola de comandos del plano de
experimento; la parada es ordenada y en sentido inverso.

Fase de implementación: Fase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Component(StrEnum):
    PLANT_SERVER = "plant_server"
    GATEWAY = "gateway"
    CONTROLLER = "controller"
    MONITOR = "monitor"
    UI = "ui"


START_ORDER: tuple[Component, ...] = (
    Component.PLANT_SERVER,
    Component.GATEWAY,
    Component.CONTROLLER,
    Component.MONITOR,
)


@dataclass(slots=True)
class ComponentStatus:
    component: Component
    pid: int | None
    alive: bool


class Launcher:
    def __init__(self, run_id: str, config_path: str, scenario_path: str) -> None:
        self.run_id = run_id
        self.config_path = config_path
        self.scenario_path = scenario_path

    def start_all(self, with_ui: bool = False) -> None:
        raise NotImplementedError("Fase 3 — RF-54: arranque de componentes")

    def stop_all(self, timeout_s: float = 10.0) -> None:
        raise NotImplementedError("Fase 3 — RF-54: parada ordenada")

    def status(self) -> list[ComponentStatus]:
        raise NotImplementedError("Fase 3 — RF-54")
