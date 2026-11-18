"""Cliente OPC UA genérico y reutilizable (RF-11, RF-14, RF-15).

Lo usan el gateway (hacia la planta), el controlador y el monitor. Ofrece conexión segura,
navegación, lectura, escritura y suscripciones, y convierte cada notificación en un
``Sample`` con SourceTimestamp, ServerTimestamp, tiempo de recepción y StatusCode.
Ante la pérdida de sesión reintenta con espera exponencial y restablece las suscripciones.

Fase de implementación: Fase 3. Dependencia prevista: asyncua.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fdisim.common.types import Sample
from fdisim.opcua.security import SecurityConfig

SampleHandler = Callable[[Sample], Awaitable[None] | None]


class OpcUaClient:
    def __init__(self, endpoint: str, security: SecurityConfig, component: str) -> None:
        self.endpoint = endpoint
        self.security = security
        self.component = component

    async def connect(self) -> None:
        raise NotImplementedError("Fase 3 — RF-11: conexión segura")

    async def disconnect(self) -> None:
        raise NotImplementedError("Fase 3 — RF-11")

    async def browse_tags(self) -> dict[str, str]:
        """Devuelve ``{tag: nodeid}`` navegando desde PlantaDosTanques."""
        raise NotImplementedError("Fase 3 — RF-11: navegación")

    async def read(self, tag: str) -> Sample:
        raise NotImplementedError("Fase 3 — RF-11: lectura")

    async def write(self, tag: str, value: float) -> None:
        raise NotImplementedError("Fase 3 — RF-11: escritura")

    async def subscribe(
        self, tags: list[str], handler: SampleHandler, publishing_interval_ms: int
    ) -> None:
        raise NotImplementedError("Fase 3 — RF-11/RF-14: suscripción con marcas de tiempo")

    async def run_with_reconnect(self) -> None:
        """Mantiene la sesión viva y reconecta con espera exponencial (≤ 5 s, RNF-07)."""
        raise NotImplementedError("Fase 3 — RF-15: reconexión")
