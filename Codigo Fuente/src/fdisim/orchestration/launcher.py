"""Lanzador de componentes como procesos independientes (RF-54).

Orden de arranque: servidor de planta (4840) → gateway (4841) → controlador → monitor →
(HMI). Cada componente es un ``multiprocessing.Process`` (contexto *spawn*) con su cola de
comandos del plano de experimento; el lanzador espera el evento READY de cada uno antes de
arrancar el siguiente. La parada es ordenada y en sentido inverso; mientras espera, el
lanzador sigue leyendo eventos para que ningún proceso quede bloqueado con datos sin entregar.

La HMI se lanza como subproceso independiente (``python -m fdisim ui``): NiceGUI no admite
ejecutarse dentro de un proceso hijo de ``multiprocessing``.

Implementado en la Fase 3.
"""

from __future__ import annotations

import logging
import multiprocessing
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from fdisim.common import paths
from fdisim.common.bus import Command, CommandType, Event, EventType, ExperimentHub
from fdisim.orchestration.components import ComponentSpec, component_main


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
    def __init__(
        self,
        run_id: str,
        config_path: str,
        scenario_path: str,
        *,
        config: dict[str, Any] | None = None,
        seed: int | None = None,
        duration_s: float | None = None,
        run_dir: Path | None = None,
        log_dir: str | Path | None = None,
        hub: ExperimentHub | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        from fdisim.common.config import load_config, load_scenario

        self.run_id = run_id
        self.config_path = config_path
        self.scenario_path = scenario_path
        self.config = config if config is not None else load_config(config_path).to_dict()
        scenario = load_scenario(scenario_path)
        self.seed = scenario.seed if seed is None else int(seed)
        self.duration_s = float(duration_s or scenario.duration_s)
        self.run_dir = Path(run_dir) if run_dir else paths.RAW_DIR / run_id
        self.log_dir = str(log_dir or self.config.get("logging", {}).get("dir", paths.LOGS_DIR))
        self.hub = hub or ExperimentHub([c.value for c in START_ORDER])
        self.logger = logger or logging.getLogger("fdisim.orchestrator")
        self.backlog: list[Event] = []
        self._procs: dict[Component, Any] = {}
        self._ui: subprocess.Popen | None = None

    # ------------------------------------------------------------------ arranque
    def start_all(self, with_ui: bool = False, ready_timeout_s: float = 60.0) -> None:
        ctx = multiprocessing.get_context("spawn")
        for component in START_ORDER:
            spec = ComponentSpec(
                component.value,
                self.run_id,
                self.config,
                str(self.scenario_path),
                self.seed,
                self.duration_s,
                str(self.run_dir),
                self.log_dir,
            )
            process = ctx.Process(
                target=component_main,
                args=(spec, self.hub.events, self.hub.commands),
                name=f"fdisim-{component.value}",
            )
            process.start()
            self._procs[component] = process
            self._wait_ready(component, ready_timeout_s)
            self.logger.info("%s listo (pid %s)", component.value, process.pid)
        if with_ui:
            self.start_ui()

    def start_ui(self) -> None:
        """Lanza la HMI web como subproceso, con la configuración efectiva de la corrida."""
        config_file = self.run_dir / "config.yaml"
        cmd = [
            sys.executable,
            "-m",
            "fdisim",
            "ui",
            "--config",
            str(config_file),
            "--run-id",
            self.run_id,
        ]
        self._ui = subprocess.Popen(cmd, cwd=paths.PROJECT_ROOT)
        self.logger.info("HMI lanzada (pid %s)", self._ui.pid)

    def _wait_ready(self, component: Component, timeout_s: float) -> None:
        deadline = time.perf_counter() + timeout_s
        process = self._procs[component]
        while True:
            for event in self.hub.drain(0.2):
                if event.type is EventType.ERROR:
                    raise RuntimeError(f"{event.source}: {event.payload}")
                if event.source == component.value and event.type is EventType.READY:
                    return
                self.backlog.append(event)
            if not process.is_alive():
                raise RuntimeError(
                    f"{component.value} terminó durante el arranque (código {process.exitcode})"
                )
            if time.perf_counter() > deadline:
                raise TimeoutError(f"{component.value} no estuvo listo en {timeout_s:.0f} s")

    # ------------------------------------------------------------------ operación
    def send(self, component: Component, command: CommandType, **payload: Any) -> None:
        self.hub.send_command(component.value, Command(command, payload))

    def dead_components(self) -> list[str]:
        return [c.value for c, p in self._procs.items() if not p.is_alive()]

    def stop_all(
        self, timeout_s: float = 15.0, on_event: Callable[[Event], None] | None = None
    ) -> None:
        handle = on_event or self.backlog.append
        if self._ui is not None and self._ui.poll() is None:
            self._ui.terminate()
            try:
                self._ui.wait(5)
            except subprocess.TimeoutExpired:
                self._ui.kill()
        for component in reversed(START_ORDER):
            process = self._procs.get(component)
            if process is None:
                continue
            if process.is_alive():
                self.hub.send_command(component.value, Command(CommandType.STOP))
            deadline = time.perf_counter() + timeout_s
            while process.is_alive() and time.perf_counter() < deadline:
                for event in self.hub.drain(0.1):
                    handle(event)
            if process.is_alive():
                self.logger.warning("%s no se detuvo a tiempo; se termina", component.value)
                process.terminate()
            process.join(5)
        for event in self.hub.drain(0.2):
            handle(event)

    def status(self) -> list[ComponentStatus]:
        out = [ComponentStatus(c, p.pid, p.is_alive()) for c, p in self._procs.items()]
        if self._ui is not None:
            out.append(ComponentStatus(Component.UI, self._ui.pid, self._ui.poll() is None))
        return out
