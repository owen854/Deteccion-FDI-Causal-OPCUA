"""Servidor OPC UA de planta — nivel de campo (RF-05, RF-06, RF-10, RF-12, RF-14).

Aloja la ``Plant`` y, en cada paso del reloj de co-simulación:

1. aplica los cambios de consigna programados en el escenario (RF-09) escribiendo LIC-102.SP;
2. lee P-101, el comando de bomba que escribió el controlador a través del gateway;
3. avanza la planta un paso Δt;
4. publica LT-101, LT-102, FT-101 y el tiempo simulado con SourceTimestamp igual al instante
   programado del paso (``CoSimClock.epoch_of``);
5. envía la verdad de terreno por el plano de experimento (nunca por OPC UA).

P-101 y LIC-102.SP pertenecen a los clientes: el servidor solo los inicializa (P-101 en el
comando de equilibrio y la consigna en su primer valor) y nunca los sobrescribe con un eco,
para no pisar una escritura concurrente del controlador o de la HMI.

Endpoint por defecto: ``opc.tcp://127.0.0.1:4840/fdisim/planta``.

Implementado en la Fase 3. Dependencia: asyncua.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import numpy as np

from fdisim.common.bus import ExperimentBus
from fdisim.common.clock import CoSimClock
from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102, GroundTruthRecord
from fdisim.control.setpoint import SetpointProfile
from fdisim.opcua.client_base import from_epoch
from fdisim.opcua.security import SecurityConfig
from fdisim.process.plant import Plant, PlantState

COMPONENT = "plant_server"
SIM_TIME = "SIM.TIME"
SIM_RUNNING = "SIM.RUNNING"
PUBLISHED_MEASUREMENTS = (LT_101, LT_102, FT_101)


class PlantServer:
    def __init__(
        self,
        endpoint: str,
        plant: Plant,
        clock: CoSimClock,
        security: SecurityConfig,
        bus: ExperimentBus,
        setpoint: SetpointProfile | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.plant = plant
        self.clock = clock
        self.security = security
        self.bus = bus
        self.setpoint = setpoint or SetpointProfile([(0.0, 25.0)])
        self.logger = logger or logging.getLogger("fdisim.plant_server")
        self.finished = False
        self._server: Any = None
        self._nodes: dict[str, Any] = {}
        self._compute_s: list[float] = []

    # ------------------------------------------------------------------ ciclo de vida
    async def start(self) -> None:
        """Inicia el servidor, construye el espacio de direcciones y aplica la seguridad."""
        from fdisim.opcua.factory import create_server

        self._server, self._nodes = await create_server(self.endpoint, self.security, COMPONENT)
        await self._server.start()
        command = self.plant.equilibrium_command()
        state = self.plant.reset(command)
        now = time.time()
        await self._write(P_101, command, now)
        await self._write(SP_102, self.setpoint.value_at(0.0), now)
        await self._publish(state, now)
        await self._write(SIM_RUNNING, False, now)
        self.logger.info(
            "Servidor de planta en %s (%s, %s); P-101 inicial %.2f %%",
            self.endpoint,
            self.security.mode.value,
            self.security.policy,
            command,
        )

    async def run(self, duration_s: float, stop: asyncio.Event | None = None) -> None:
        """Bucle de co-simulación: consigna → comando → paso de planta → publicación → verdad."""
        changes = deque(self.setpoint.change_times())
        dt = self.clock.dt_s
        await self._write(SIM_RUNNING, True, time.time())
        self.logger.info(
            "Co-simulación iniciada: %.0f s simulados, Δt = %.3f s, escala %.1f×",
            duration_s,
            dt,
            self.clock.time_scale,
        )
        async for t_end in self.clock.ticks(duration_s):
            t_start = t_end - dt
            while changes and changes[0] <= t_start + 1e-9:
                t_change = changes.popleft()
                value = self.setpoint.value_at(t_change)
                await self._write(SP_102, value, self.clock.epoch_of(t_change))
                self.logger.info("Consigna programada: %.2f cm en t = %.1f s", value, t_change)
            command = self._read(P_101)
            t0 = time.perf_counter()
            state = self.plant.step(command)
            self._compute_s.append(time.perf_counter() - t0)
            epoch = self.clock.epoch_of(state.sim_time)
            await self._publish(state, epoch)
            self.bus.publish_ground_truth(self._ground_truth(state, epoch))
            if stop is not None and stop.is_set():
                self.logger.warning("Co-simulación detenida en t = %.1f s", state.sim_time)
                break
        await self._write(SIM_RUNNING, False, time.time())
        self.finished = True
        stats = self.stats()
        self.logger.info(
            "Co-simulación terminada: %d pasos, %d atrasados, deriva %.4f %%, cómputo p99 %.3f ms",
            stats["clock"]["steps"],
            stats["clock"]["overruns"],
            stats["clock"]["drift_pct"],
            stats["compute_ms"]["p99"],
        )

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop()
            self._server = None

    # ------------------------------------------------------------------ utilidades
    def stats(self) -> dict[str, Any]:
        compute = np.asarray(self._compute_s) * 1000.0
        pct = (
            {
                "mean": float(compute.mean()),
                "p99": float(np.percentile(compute, 99)),
                "max": float(compute.max()),
            }
            if compute.size
            else {"mean": 0.0, "p99": 0.0, "max": 0.0}
        )
        return {
            "clock": self.clock.stats.as_dict(),
            "start_epoch": self.clock.start_epoch,
            "time_scale": self.clock.time_scale,
            "dt_s": self.clock.dt_s,
            "compute_ms": pct,
            "limit_ms": 100.0 * self.clock.dt_s,  # RNF-01: 10 % de Δt
        }

    def _ground_truth(self, state: PlantState, epoch: float) -> GroundTruthRecord:
        setpoint = self._read(SP_102)
        true = dict(state.true_values)
        measured = dict(state.measured_values)
        true[SP_102] = setpoint
        measured[SP_102] = setpoint
        return GroundTruthRecord(state.sim_time, true, measured, source_ts=epoch)

    async def _publish(self, state: PlantState, epoch: float) -> None:
        for tag in PUBLISHED_MEASUREMENTS:
            await self._write(tag, state.measured_values[tag], epoch)
        await self._write(SIM_TIME, state.sim_time, epoch)

    def _read(self, tag: str) -> float:
        return float(self._server.read_attribute_value(self._nodes[tag].nodeid).Value.Value)

    async def _write(self, tag: str, value: float | bool, epoch: float) -> None:
        from asyncua import ua

        variant = (
            ua.Variant(bool(value), ua.VariantType.Boolean)
            if tag == SIM_RUNNING
            else ua.Variant(float(value), ua.VariantType.Double)
        )
        dv = ua.DataValue(
            variant, SourceTimestamp=from_epoch(epoch), ServerTimestamp=from_epoch(time.time())
        )
        await self._server.write_attribute_value(self._nodes[tag].nodeid, dv)
