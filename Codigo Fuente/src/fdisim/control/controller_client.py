"""Soft-PLC: controlador PID como cliente OPC UA independiente (RF-08).

Se conecta al **gateway** (no a la planta), se suscribe a LT-102, a LIC-102.SP y al estado de la
simulación (no calcula mientras la co-simulación no corre, para no acumular error), ejecuta el PID
cada ``ts_s`` de tiempo simulado (``ts_s / time_scale`` de pared) y escribe P-101. Como recibe
los datos por el mismo canal que el monitor, un ataque FDI en el gateway afecta realmente al
lazo cerrado y al proceso físico.

Sin datos frescos (pérdida de red o del gateway) el controlador **no** actualiza la salida:
mantiene el último comando, lo registra en la bitácora y lo cuenta (criterio de RF-08).
Al recuperar la sesión, el cliente restablece las suscripciones y el lazo continúa.

Implementado en la Fase 3. Dependencia: asyncua.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from fdisim.common.types import SP_102, Sample
from fdisim.control.pid import PIDController
from fdisim.opcua.client_base import OpcUaClient
from fdisim.opcua.plant_server import SIM_RUNNING
from fdisim.opcua.security import SecurityConfig

COMPONENT = "controller"


class ControllerClient:
    def __init__(
        self,
        endpoint: str,
        pid: PIDController,
        controlled_tag: str,
        manipulated_tag: str,
        *,
        security: SecurityConfig | None = None,
        client: OpcUaClient | None = None,
        time_scale: float = 1.0,
        publishing_interval_ms: float = 100.0,
        stale_periods: float = 3.0,
        logger: logging.Logger | None = None,
    ) -> None:
        if client is None and security is None:
            raise ValueError("Indique security o un cliente OPC UA ya configurado")
        self.endpoint = endpoint
        self.pid = pid
        self.controlled_tag = controlled_tag
        self.manipulated_tag = manipulated_tag
        self.time_scale = time_scale
        self.publishing_interval_ms = publishing_interval_ms
        self.logger = logger or logging.getLogger("fdisim.controller")
        self.client = client or OpcUaClient(
            endpoint,
            security,
            COMPONENT,
            "gateway",
            logger=self.logger,  # type: ignore[arg-type]
        )
        self.period_s = pid.params.ts_s / time_scale
        self.stale_after_s = stale_periods * self.period_s
        self.updates = 0
        self.stale_cycles = 0
        self.failed_writes = 0
        self._latest: dict[str, Sample] = {}
        self._stop = asyncio.Event()
        self._was_stale = False

    @property
    def output(self) -> float:
        return self.pid.last_output

    async def start(self) -> None:
        """Conecta, inicializa el PID sin salto (bumpless) y se suscribe."""
        await self.client.connect_with_retry()
        current = await self.client.read(self.manipulated_tag)
        self.pid.reset(initial_output=current.value)
        tags = (self.controlled_tag, SP_102, SIM_RUNNING)
        await self.client.subscribe(tags, self._on_sample, self.publishing_interval_ms)
        for tag in tags:
            self._latest[tag] = await self.client.read(tag)
        self.logger.info(
            "Controlador conectado a %s: Ts = %.2f s (%.3f s de pared), salida inicial %.2f %%",
            self.endpoint,
            self.pid.params.ts_s,
            self.period_s,
            current.value,
        )

    async def run(self) -> None:
        """Bucle de control: suscripción → PID → escritura, hasta recibir ``stop``."""
        if not self.client.connected:
            await self.start()
        watchdog = asyncio.create_task(self.client.run_with_reconnect(self._stop))
        next_tick = time.perf_counter()
        try:
            while not self._stop.is_set():
                next_tick += self.period_s
                await self._cycle()
                delay = next_tick - time.perf_counter()
                if delay < 0:  # atraso: se re-sincroniza sin acumular ciclos pendientes
                    next_tick = time.perf_counter()
                    delay = 0.0
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
        finally:
            self._stop.set()
            await watchdog

    async def stop(self) -> None:
        self._stop.set()
        await self.client.disconnect()

    def stats(self) -> dict[str, Any]:
        return {
            "updates": self.updates,
            "stale_cycles": self.stale_cycles,
            "failed_writes": self.failed_writes,
            "reconnections": self.client.reconnections,
            "recovery_s": list(self.client.recovery_times_s),
            "last_output_pct": self.pid.last_output,
        }

    # ------------------------------------------------------------------
    def _on_sample(self, sample: Sample) -> None:
        if sample.status == "Good":
            self._latest[sample.tag] = sample

    async def _cycle(self) -> None:
        running = self._latest.get(SIM_RUNNING)
        if self.client.connected and running is not None and not running.value:
            return  # simulación detenida o aún sin iniciar: el PID espera sin acumular error
        y = self._latest.get(self.controlled_tag)
        sp = self._latest.get(SP_102)
        now = time.time()
        fresh = y is not None and now - y.received_ts <= self.stale_after_s
        if not fresh or sp is None or not self.client.connected:
            self.stale_cycles += 1
            if not self._was_stale:
                self.logger.warning(
                    "Sin datos frescos de %s: se mantiene P-101 = %.2f %%",
                    self.controlled_tag,
                    self.pid.last_output,
                )
            self._was_stale = True
            return
        if self._was_stale:
            self.logger.warning("Datos de %s restablecidos; el lazo continúa", self.controlled_tag)
            self._was_stale = False
        command = self.pid.update(sp.value, y.value)
        self.updates += 1
        try:
            await self.client.write(self.manipulated_tag, command)
        except Exception as exc:
            self.failed_writes += 1
            self.logger.warning("No se pudo escribir %s: %s", self.manipulated_tag, exc)
