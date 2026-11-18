"""Servidor OPC UA de planta — nivel de campo (RF-10, RF-12, RF-14).

Aloja la ``Plant`` y, en cada paso del reloj de co-simulación, publica las mediciones en el
espacio de direcciones con SourceTimestamp. Lee P-101 y LIC-102.SP escritos por los clientes
y los aplica a la planta. Endpoint por defecto: ``opc.tcp://127.0.0.1:4840/fdisim/planta``.

Fase de implementación: Fase 3. Dependencia prevista: asyncua.
"""

from __future__ import annotations

from fdisim.common.bus import ExperimentBus
from fdisim.common.clock import CoSimClock
from fdisim.opcua.security import SecurityConfig
from fdisim.process.plant import Plant


class PlantServer:
    def __init__(
        self,
        endpoint: str,
        plant: Plant,
        clock: CoSimClock,
        security: SecurityConfig,
        bus: ExperimentBus,
    ) -> None:
        self.endpoint = endpoint
        self.plant = plant
        self.clock = clock
        self.security = security
        self.bus = bus

    async def start(self) -> None:
        """Inicia el servidor, construye el espacio de direcciones y aplica la seguridad."""
        raise NotImplementedError("Fase 3 — RF-10/RF-12: servidor de planta")

    async def run(self, duration_s: float) -> None:
        """Bucle de co-simulación: paso de planta → publicación → verdad de terreno."""
        raise NotImplementedError("Fase 3 — RF-05/RF-06: bucle de co-simulación")

    async def stop(self) -> None:
        raise NotImplementedError("Fase 3")
