"""Gateway OPC UA agregador — nodo intermedio comprometible (RF-13, RF-16).

Es a la vez cliente del servidor de planta y servidor para el controlador y el monitor
(``opc.tcp://127.0.0.1:4841/fdisim/gateway``). Replica el espacio de direcciones y
retransmite lecturas (planta → clientes) y escrituras (clientes → planta).

Cada valor de planta pasa por el ``FdiInjector`` antes de publicarse. Sin ataque activo,
el gateway es transparente. Con ataque, los clientes reciben datos falsos firmados y cifrados
con las credenciales legítimas del gateway (Informe OE1 §3.6).

Fase de implementación: Fase 3 (modo transparente) y Fase 4 (inyección).
"""

from __future__ import annotations

from fdisim.attacks.injector import FdiInjector
from fdisim.common.bus import ExperimentBus
from fdisim.opcua.client_base import OpcUaClient
from fdisim.opcua.security import SecurityConfig


class AggregatingGateway:
    def __init__(
        self,
        endpoint: str,
        upstream: OpcUaClient,
        injector: FdiInjector,
        security: SecurityConfig,
        bus: ExperimentBus,
    ) -> None:
        self.endpoint = endpoint
        self.upstream = upstream
        self.injector = injector
        self.security = security
        self.bus = bus

    async def start(self) -> None:
        raise NotImplementedError("Fase 3 — RF-13: gateway agregador")

    async def relay_forever(self) -> None:
        """Retransmite planta → clientes (vía inyector) y clientes → planta."""
        raise NotImplementedError("Fase 3/4 — RF-13/RF-16: retransmisión e inyección")

    async def stop(self) -> None:
        raise NotImplementedError("Fase 3")
