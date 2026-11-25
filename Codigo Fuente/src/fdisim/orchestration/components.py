"""Punto de entrada de cada componente en su propio proceso (RF-54, RF-55).

``component_main`` es la función que ejecuta ``multiprocessing`` (contexto *spawn*) para cada
componente. Configura la bitácora de la corrida, construye el componente desde la
configuración efectiva y atiende los comandos del plano de experimento:

- planta: arranca el servidor, publica READY, espera START, corre la duración del escenario y
  publica FINISHED; sigue sirviendo hasta STOP;
- gateway, controlador y monitor: conectan, publican READY y trabajan hasta STOP.

Al detenerse, cada componente publica sus estadísticas (STATS). Un fallo se publica como ERROR
y termina el proceso con código 1.

Implementado en la Fase 3.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import signal
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdisim.common.bus import Command, CommandType, EventType, ExperimentBus
from fdisim.common.logging_setup import configure_logging
from fdisim.opcua.factory import endpoint_url
from fdisim.opcua.security import SecurityConfig


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """Argumentos (serializables) con los que el orquestador lanza un componente."""

    component: str
    run_id: str
    config: dict[str, Any]
    scenario_path: str
    seed: int
    duration_s: float
    run_dir: str
    log_dir: str


def plant_endpoint(config: Mapping[str, Any]) -> str:
    opcua = config["opcua"]
    ps = opcua["plant_server"]
    return endpoint_url(opcua["host"], int(ps["port"]), ps["path"])


def gateway_endpoint(config: Mapping[str, Any]) -> str:
    opcua = config["opcua"]
    gw = opcua["gateway"]
    return endpoint_url(opcua["host"], int(gw["port"]), gw["path"])


def security_of(config: Mapping[str, Any]) -> SecurityConfig:
    return SecurityConfig.from_config(config["opcua"]["security"])


def client_options(config: Mapping[str, Any]) -> dict[str, float]:
    rec = config["opcua"].get("reconnect", {})
    return {
        "initial_delay_s": float(rec.get("initial_delay_s", 0.5)),
        "max_delay_s": float(rec.get("max_delay_s", 5.0)),
    }


def publishing_interval(config: Mapping[str, Any]) -> float:
    """Intervalo de publicación de las suscripciones de los clientes del gateway [ms]."""
    return float(config["opcua"].get("subscription", {}).get("publishing_interval_ms", 100))


def gateway_publishing_interval(config: Mapping[str, Any]) -> float:
    """Intervalo del enlace interno gateway ← planta [ms] (por defecto, el de los clientes)."""
    sub = config["opcua"].get("subscription", {})
    return float(sub.get("gateway_publishing_interval_ms", publishing_interval(config)))


def component_main(spec: ComponentSpec, events: Any, commands: Mapping[str, Any]) -> None:
    # Ctrl+C lo atiende solo el orquestador, que detiene los componentes en orden y así cada uno
    # alcanza a guardar sus datos y publicar sus estadísticas.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    level = str(spec.config.get("logging", {}).get("level", "INFO"))
    logger = configure_logging(spec.component, spec.run_id, level, spec.log_dir)
    bus = ExperimentBus(spec.component, events, commands)
    try:
        asyncio.run(_RUNNERS[spec.component](spec, bus, logger))
    except Exception as exc:
        logger.exception("Fallo del componente %s", spec.component)
        bus.publish(EventType.ERROR, f"{exc.__class__.__name__}: {exc}")
        raise SystemExit(1) from exc


class _Commands:
    """Atiende la cola de comandos del componente desde el bucle asyncio."""

    def __init__(
        self, bus: ExperimentBus, on_command: Callable[[Command], None] | None = None
    ) -> None:
        self.bus = bus
        self.on_command = on_command
        self.start = asyncio.Event()
        self.stop = asyncio.Event()
        self._task = asyncio.create_task(self._poll())

    async def _poll(self) -> None:
        parent = multiprocessing.parent_process()
        while not self.stop.is_set():
            if parent is not None and not parent.is_alive():
                self.stop.set()  # el orquestador murió: no dejar procesos huérfanos
                return
            for command in self.bus.poll_commands():
                if command.type is CommandType.START:
                    self.start.set()
                elif command.type is CommandType.STOP:
                    self.stop.set()
                elif self.on_command is not None:
                    try:
                        self.on_command(command)
                    except Exception:
                        logging.getLogger("fdisim").exception("Comando %s rechazado", command.type)
            await asyncio.sleep(0.05)

    async def first_of_start_or_stop(self) -> None:
        waits = [asyncio.create_task(self.start.wait()), asyncio.create_task(self.stop.wait())]
        _, pending = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    async def close(self) -> None:
        self.stop.set()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


async def _run_plant(spec: ComponentSpec, bus: ExperimentBus, logger: logging.Logger) -> None:
    from fdisim.common.clock import CoSimClock
    from fdisim.common.config import load_scenario
    from fdisim.control.setpoint import SetpointProfile
    from fdisim.opcua.plant_server import PlantServer
    from fdisim.process.disturbances import DisturbanceSchedule
    from fdisim.process.plant import Plant

    cfg = spec.config
    sim = cfg["simulation"]
    scenario = load_scenario(spec.scenario_path)
    dt = float(sim["dt_s"])
    plant = Plant.from_config(
        cfg["plant"],
        dt,
        spec.seed,
        DisturbanceSchedule.from_config(scenario.disturbances),
        str(sim.get("integrator", "solve_ivp")),
    )
    server = PlantServer(
        plant_endpoint(cfg),
        plant,
        CoSimClock(dt, float(sim["time_scale"])),
        security_of(cfg),
        bus,
        SetpointProfile(scenario.setpoint_profile),
        logger,
    )
    await server.start()
    commands = _Commands(bus)
    bus.publish(EventType.READY)
    try:
        await commands.first_of_start_or_stop()
        if commands.start.is_set() and not commands.stop.is_set():
            await server.run(spec.duration_s, commands.stop)
            bus.publish(EventType.FINISHED, server.stats())
        await commands.stop.wait()
    finally:
        await server.stop()
        await commands.close()
    bus.publish(EventType.STATS, server.stats())


async def _run_gateway(spec: ComponentSpec, bus: ExperimentBus, logger: logging.Logger) -> None:
    from fdisim.attacks.injector import FdiInjector
    from fdisim.attacks.scheduler import AttackScheduler
    from fdisim.common.config import load_scenario
    from fdisim.opcua.client_base import OpcUaClient
    from fdisim.opcua.gateway import COMPONENT, AggregatingGateway

    cfg = spec.config
    security = security_of(cfg)
    scenario = load_scenario(spec.scenario_path)
    # El gateway comprometido lleva siempre el inyector: transparente mientras no haya ataques
    # activos, listo para los del escenario y para los que se armen en caliente (RF-23).
    injector = FdiInjector(AttackScheduler(list(scenario.attacks)), bus)
    upstream = OpcUaClient(
        plant_endpoint(cfg),
        security,
        COMPONENT,
        "plant_server",
        logger=logger,
        **client_options(cfg),
    )
    gateway = AggregatingGateway(
        gateway_endpoint(cfg),
        upstream,
        injector,
        security,
        bus,
        gateway_publishing_interval(cfg),
        logger,
        time_scale=float(cfg["simulation"]["time_scale"]),
    )
    await gateway.start()
    if scenario.attacks:
        logger.warning(
            "Ataques programados: %s",
            "; ".join(
                f"{a.attack_id} {a.type.value} sobre {','.join(a.targets)} en "
                f"[{a.start_s:.0f}, {a.end_s:.0f}) s"
                for a in scenario.attacks
            ),
        )

    def on_command(command: Command) -> None:
        if command.type is CommandType.ARM_ATTACK:
            gateway.arm_attack(command.payload["spec"], bool(command.payload.get("start_now")))
        elif command.type is CommandType.DISARM_ATTACK:
            gateway.disarm_attack(str(command.payload["attack_id"]))

    commands = _Commands(bus, on_command)
    bus.publish(EventType.READY)
    try:
        await gateway.relay_forever(commands.stop)
    finally:
        await gateway.stop()
        await commands.close()
    bus.publish(EventType.STATS, gateway.stats())


async def _run_controller(spec: ComponentSpec, bus: ExperimentBus, logger: logging.Logger) -> None:
    from fdisim.control.controller_client import COMPONENT, ControllerClient
    from fdisim.control.pid import PIDController, PIDParams
    from fdisim.opcua.client_base import OpcUaClient

    cfg = spec.config
    control = cfg["control"]
    client = OpcUaClient(
        gateway_endpoint(cfg),
        security_of(cfg),
        COMPONENT,
        "gateway",
        logger=logger,
        **client_options(cfg),
    )
    controller = ControllerClient(
        gateway_endpoint(cfg),
        PIDController(PIDParams.from_config(control)),
        str(control["controlled_tag"]),
        str(control["manipulated_tag"]),
        client=client,
        time_scale=float(cfg["simulation"]["time_scale"]),
        publishing_interval_ms=publishing_interval(cfg),
        logger=logger,
    )
    await controller.start()
    commands = _Commands(bus)
    loop = asyncio.create_task(controller.run())
    bus.publish(EventType.READY)
    try:
        await commands.stop.wait()
    finally:
        await controller.stop()
        await loop
        await commands.close()
    bus.publish(EventType.STATS, controller.stats())


async def _run_monitor(spec: ComponentSpec, bus: ExperimentBus, logger: logging.Logger) -> None:
    from pathlib import Path

    from fdisim.data.historian import Historian
    from fdisim.detection.online_monitor import OnlineMonitor
    from fdisim.opcua.client_base import OpcUaClient

    cfg = spec.config
    client = OpcUaClient(
        gateway_endpoint(cfg),
        security_of(cfg),
        "monitor",
        "gateway",
        logger=logger,
        **client_options(cfg),
    )
    historian = Historian(Path(spec.run_dir), fmt=str(cfg.get("data", {}).get("format", "parquet")))
    detectors = _online_detectors(cfg, logger)

    def publish_result(kind: str, result: Any) -> None:
        bus.publish(EventType.DETECTION, detection_payload(kind, result))

    monitor = OnlineMonitor(
        client,
        detectors,
        historian,
        float(cfg.get("detection", {}).get("period_s", 0.5)),
        on_result=publish_result,
        publishing_interval_ms=publishing_interval(cfg),
        time_scale=float(cfg.get("simulation", {}).get("time_scale", 1.0)),
        logger=logger,
    )
    await monitor.start()
    commands = _Commands(bus)
    loop = asyncio.create_task(monitor.run())
    bus.publish(EventType.READY)
    try:
        await commands.stop.wait()
    finally:
        await monitor.stop()
        await loop
        await commands.close()
    bus.publish(EventType.STATS, monitor.stats())


def _online_detectors(cfg: Mapping[str, Any], logger: logging.Logger) -> list[Any]:
    """Detector causal y método base calibrados; sin modelo, el monitor solo registra."""
    from fdisim.detection.pipeline import load_detectors, model_available, model_dir_of

    if not model_available(cfg):
        logger.warning("Sin modelo causal en %s: el monitor solo registra", model_dir_of(cfg))
        return []
    try:
        return load_detectors(cfg, calibrate=False)
    except Exception as exc:
        logger.warning("Detectores no disponibles (%s): el monitor solo registra", exc)
        return []


def detection_payload(kind: str, result: Any) -> dict[str, Any]:
    """Salida compacta de un detector para el plano de experimento (HMI, RF-49)."""
    return {
        "t": result.t,
        "detector": kind,
        "alarm": bool(result.alarm),
        "suspected": result.suspected_tag,
        "triggered": list(result.triggered),
        "scores": {k: v for k, v in result.scores.items() if not k.startswith("ewma:")},
        "alarms": [
            {
                "alarm_id": a.alarm_id,
                "detector": a.detector.value,
                "kind": a.kind.value,
                "t": a.t,
                "t_end": a.t_end,
                "variables": list(a.variables),
                "score": a.score,
                "suspected_tag": a.suspected_tag,
                "state": a.state.value,
            }
            for a in result.alarms
        ],
    }


_RUNNERS: dict[str, Callable[[ComponentSpec, ExperimentBus, logging.Logger], Awaitable[None]]] = {
    "plant_server": _run_plant,
    "gateway": _run_gateway,
    "controller": _run_controller,
    "monitor": _run_monitor,
}
