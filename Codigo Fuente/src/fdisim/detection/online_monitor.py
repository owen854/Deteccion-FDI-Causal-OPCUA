"""Monitor OPC UA en línea: cliente de supervisión que alimenta a los detectores (RF-38).

Se suscribe a las variables del gateway (mismo canal que el controlador), alinea las muestras
en la rejilla ``detection.period_s``, ejecuta en paralelo el detector causal y el método base,
mide el tiempo de procesamiento por muestra (RF-42) y publica resultados al historiador y a
la HMI. Puede ejecutarse sin interfaz (campañas) o dentro del proceso de la HMI.

Fase de implementación: Fase 6.
"""

from __future__ import annotations

from collections.abc import Callable

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
    ) -> None:
        self.client = client
        self.detectors = detectors
        self.historian = historian
        self.period_s = period_s
        self.on_result = on_result

    async def run(self) -> None:
        raise NotImplementedError("Fase 6 — RF-38: detección en línea")

    async def stop(self) -> None:
        raise NotImplementedError("Fase 6")
