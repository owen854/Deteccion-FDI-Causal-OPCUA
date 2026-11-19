"""Enlace OPC UA de la HMI: cliente del gateway con la identidad ``hmi`` (RF-09, RF-47).

La HMI es un cliente OPC UA más, igual que el controlador y el monitor: ve exactamente los datos
que publica el gateway (incluidos, desde la Fase 4, los falsificados). Mantiene la conexión
viva (reintenta mientras el gateway no esté disponible), vuelca cada notificación en el
``UiState`` y permite cambiar la consigna LIC-102.SP (RF-09).

Implementado en la Fase 3.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from typing import Any

from fdisim.common.types import PROCESS_TAGS, SP_102
from fdisim.opcua.client_base import OpcUaClient
from fdisim.opcua.information_model import variable_by_tag
from fdisim.opcua.plant_server import SIM_RUNNING, SIM_TIME
from fdisim.orchestration.components import (
    client_options,
    gateway_endpoint,
    publishing_interval,
    security_of,
)
from fdisim.ui.state import UiState

HMI_TAGS: tuple[str, ...] = (*PROCESS_TAGS, SIM_TIME, SIM_RUNNING)


class HmiLink:
    def __init__(
        self, config: Mapping[str, Any], state: UiState, logger: logging.Logger | None = None
    ) -> None:
        self.state = state
        self.logger = logger or logging.getLogger("fdisim.hmi")
        self.endpoint = gateway_endpoint(config)
        self.security = security_of(config)
        self.publishing_ms = max(publishing_interval(config), 250.0)
        self.client = OpcUaClient(
            self.endpoint,
            self.security,
            "hmi",
            "gateway",
            logger=self.logger,
            **client_options(config),
        )
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return self.client.connected

    async def start(self) -> None:
        self._task = asyncio.create_task(self._keep_alive())

    async def stop(self) -> None:
        self._stop.set()
        await self.client.disconnect()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def write_setpoint(self, value: float) -> str:
        """Escribe la consigna si está dentro de su rango de ingeniería; devuelve un mensaje."""
        low, high = variable_by_tag(SP_102).eu_range or (0.0, 50.0)
        if not low <= value <= high:
            return f"La consigna debe estar entre {low:g} y {high:g} cm"
        if not self.client.connected:
            return "Sin conexión con el gateway"
        await self.client.write(SP_102, value)
        self.logger.info("Consigna cambiada desde la HMI: %.2f cm", value)
        return f"Consigna enviada: {value:.2f} cm"

    async def _keep_alive(self) -> None:
        await self.client.subscribe(HMI_TAGS, self.state.push_sample, self.publishing_ms)
        while not self._stop.is_set():
            try:
                await self.client.connect_with_retry(deadline_s=3600.0)
                self.state.connection_status["gateway"] = "conectado"
                await self.client.run_with_reconnect(self._stop)
            except Exception as exc:  # el gateway aún no existe o se cayó del todo
                self.state.connection_status["gateway"] = "sin conexión"
                self.logger.warning("HMI sin conexión con %s: %s", self.endpoint, exc)
                await asyncio.sleep(2.0)
