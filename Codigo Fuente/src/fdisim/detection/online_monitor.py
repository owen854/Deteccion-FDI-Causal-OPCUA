"""Monitor OPC UA en línea: cliente de supervisión que alimenta a los detectores (RF-25, RF-38).

Se suscribe a las variables del gateway (mismo canal que el controlador) con una notificación
por paso publicado y registra cada muestra en el historiador con sus tres marcas de tiempo y
su StatusCode (RF-14, RF-25). Es la «vista del supervisor»: el detector solo verá lo que llega
por OPC UA.

- **Fase 3:** modo de registro (sin detectores).
- **Fase 6:** alineará las muestras en la rejilla ``detection.period_s``, ejecutará en paralelo
  el detector causal y el método base, medirá el tiempo de procesamiento por muestra (RF-42) y
  publicará resultados al historiador y a la HMI.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fdisim.common.types import PROCESS_TAGS, Sample
from fdisim.data.historian import Historian
from fdisim.detection.base import DetectionResult, Detector
from fdisim.opcua.client_base import OpcUaClient


class OnlineMonitor:
    def __init__(
        self,
        client: OpcUaClient,
        detectors: list[Detector],
        historian: Historian,
        period_s: float,
        on_result: Callable[[str, DetectionResult], None] | None = None,
        *,
        tags: tuple[str, ...] = PROCESS_TAGS,
        publishing_interval_ms: float = 100.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.detectors = detectors
        self.historian = historian
        self.period_s = period_s
        self.on_result = on_result
        self.tags = tags
        self.publishing_interval_ms = publishing_interval_ms
        self.logger = logger or logging.getLogger("fdisim.monitor")
        self.received = 0
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self.detectors:
            raise NotImplementedError("Fase 6 — RF-38: detección en línea")
        await self.client.connect_with_retry()
        await self.client.subscribe(
            self.tags, self._on_sample, self.publishing_interval_ms, every_update=True
        )
        self.logger.info("Monitor suscrito a %s en %s", ", ".join(self.tags), self.client.endpoint)

    async def run(self) -> None:
        if not self.client.connected:
            await self.start()
        await self.client.run_with_reconnect(self._stop)

    async def stop(self) -> None:
        self._stop.set()
        await self.client.disconnect()
        self.historian.close()
        self.logger.info("Monitor detenido: %d muestras registradas", self.received)

    def stats(self) -> dict[str, Any]:
        return {
            "samples": self.received,
            "reconnections": self.client.reconnections,
            "recovery_s": list(self.client.recovery_times_s),
        }

    def _on_sample(self, sample: Sample) -> None:
        self.historian.record_sample(sample)
        self.received += 1
