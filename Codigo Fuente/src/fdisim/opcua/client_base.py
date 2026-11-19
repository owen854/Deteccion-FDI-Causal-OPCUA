"""Cliente OPC UA genérico y reutilizable (RF-11, RF-14, RF-15).

Lo usan el gateway (hacia la planta), el controlador, el monitor y la HMI. Ofrece conexión
segura, navegación, lectura, escritura y suscripciones, y convierte cada notificación en un
``Sample`` con SourceTimestamp, ServerTimestamp, tiempo de recepción y StatusCode.

Suscripciones: con ``every_update=True`` el elemento monitoreado usa el disparador
StatusValueTimestamp, de modo que llega una notificación por cada paso publicado aunque el
valor no cambie; la cola del servidor no se limita (``queuesize=0``), así que no se pierden
muestras entre dos publicaciones.

Reconexión (RF-15, RNF-07): ``run_with_reconnect`` vigila la sesión; si se pierde, reintenta con
espera exponencial (``initial_delay_s`` → ``max_delay_s``) y restablece las suscripciones.

Implementado en la Fase 3. Dependencia: asyncua.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdisim.common.types import Sample
from fdisim.opcua.information_model import (
    NAMESPACE_URI,
    PLANT_VARIABLES,
    ROOT_OBJECT,
    STATUS_VARIABLES,
)
from fdisim.opcua.security import SecurityConfig

SampleHandler = Callable[[Sample], Awaitable[None] | None]
_SPECS = {spec.tag: spec for spec in PLANT_VARIABLES + STATUS_VARIABLES}
_TAG_BY_NODE_NAME = {spec.node_name: spec.tag for spec in _SPECS.values()}


def to_epoch(value: datetime | None) -> float:
    """Marca de tiempo OPC UA → segundos de época Unix (``nan`` si falta)."""
    if value is None:
        return float("nan")
    if value.tzinfo is None:  # asyncua puede entregar fechas UTC sin zona
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def from_epoch(epoch: float | None) -> datetime | None:
    """Época Unix → marca de tiempo OPC UA (``None`` si no hay marca)."""
    if epoch is None or not math.isfinite(epoch):
        return None
    return datetime.fromtimestamp(epoch, UTC)


def sample_from_datavalue(tag: str, dv: Any, received_ts: float | None = None) -> Sample:
    raw = dv.Value.Value if dv.Value is not None else None
    value = float(raw) if raw is not None else float("nan")
    status = dv.StatusCode.name if dv.StatusCode is not None else "Good"
    return Sample(
        tag=tag,
        value=value,
        source_ts=to_epoch(dv.SourceTimestamp),
        server_ts=to_epoch(dv.ServerTimestamp),
        received_ts=time.time() if received_ts is None else received_ts,
        status=status,
    )


@dataclass(slots=True)
class _Subscription:
    tags: tuple[str, ...]
    handler: SampleHandler
    publishing_interval_ms: float
    every_update: bool


class _Handler:
    """Adaptador de asyncua: notificación → ``Sample`` → manejador del usuario."""

    def __init__(self, owner: OpcUaClient, spec: _Subscription) -> None:
        self.owner = owner
        self.spec = spec

    def datachange_notification(self, node: Any, val: Any, data: Any) -> None:
        received = time.time()
        tag = self.owner.tag_of(node.nodeid)
        if tag is None:
            return
        sample = sample_from_datavalue(tag, data.monitored_item.Value, received)
        result = self.spec.handler(sample)
        if inspect.isawaitable(result):
            self.owner._keep(asyncio.ensure_future(result))

    def status_change_notification(self, status: Any) -> None:
        self.owner.logger.warning("Cambio de estado de la suscripción: %s", status)


class OpcUaClient:
    def __init__(
        self,
        endpoint: str,
        security: SecurityConfig,
        component: str,
        server_component: str = "gateway",
        *,
        timeout_s: float = 4.0,
        initial_delay_s: float = 0.5,
        max_delay_s: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.security = security
        self.component = component
        self.server_component = server_component
        self.timeout_s = timeout_s
        self.initial_delay_s = initial_delay_s
        self.max_delay_s = max_delay_s
        self.logger = logger or logging.getLogger(f"fdisim.{component}.cliente")
        self.reconnections = 0
        self.recovery_times_s: list[float] = []
        self._client: Any = None
        self._ns: int | None = None
        self._nodes: dict[str, Any] = {}
        self._tags_by_nodeid: dict[Any, str] = {}
        self._subscriptions: list[_Subscription] = []
        self._tasks: set[asyncio.Future] = set()
        self._closing = False

    # ------------------------------------------------------------------ conexión
    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        from asyncua import ua

        from fdisim.opcua.factory import create_client

        self._closing = False
        if self._client is not None:
            return
        client = await create_client(
            self.endpoint, self.security, self.component, self.server_component, self.timeout_s
        )
        await client.connect()
        try:
            self._ns = await client.get_namespace_index(NAMESPACE_URI)
            self._nodes = {
                tag: client.get_node(ua.NodeId(spec.node_name, self._ns))
                for tag, spec in _SPECS.items()
            }
            self._tags_by_nodeid = {node.nodeid: tag for tag, node in self._nodes.items()}
            self._client = client
            for spec in self._subscriptions:
                await self._create_subscription(spec)
        except Exception:
            self._client = None
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise
        self.logger.info("Conectado a %s como '%s'", self.endpoint, self.component)

    async def connect_with_retry(self, deadline_s: float = 30.0) -> None:
        """Intenta conectar con espera exponencial hasta ``deadline_s``."""
        start = time.perf_counter()
        delay = self.initial_delay_s
        while True:
            try:
                await self.connect()
                return
            except Exception as exc:
                if time.perf_counter() - start + delay > deadline_s:
                    raise ConnectionError(
                        f"No fue posible conectar a {self.endpoint}: {exc}"
                    ) from exc
                self.logger.info(
                    "Conexión a %s fallida (%s); reintento en %.1f s",
                    self.endpoint,
                    exc.__class__.__name__,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_delay_s)

    async def disconnect(self) -> None:
        self._closing = True
        await self._drop_client()

    async def _drop_client(self, timeout_s: float | None = None) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.disconnect(), timeout=timeout_s or self.timeout_s)

    def _require(self) -> Any:
        if self._client is None:
            raise ConnectionError(f"Sin sesión OPC UA con {self.endpoint}")
        return self._client

    def tag_of(self, nodeid: Any) -> str | None:
        return self._tags_by_nodeid.get(nodeid)

    def _keep(self, task: asyncio.Future) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ servicios
    async def browse_tags(self) -> dict[str, str]:
        """Devuelve ``{tag: nodeid}`` navegando desde PlantaDosTanques."""
        from asyncua import ua

        client = self._require()
        root = client.get_node(ua.NodeId(ROOT_OBJECT, self._ns))
        found: dict[str, str] = {}
        pending = [root]
        while pending:
            node = pending.pop()
            for child in await node.get_children():
                node_class = await child.read_node_class()
                if node_class == ua.NodeClass.Object:
                    pending.append(child)
                elif node_class == ua.NodeClass.Variable:
                    tag = _TAG_BY_NODE_NAME.get(str(child.nodeid.Identifier))
                    if tag is not None:
                        found[tag] = child.nodeid.to_string()
        return found

    async def read(self, tag: str) -> Sample:
        node = self._node(tag)
        dv = await node.read_data_value()
        return sample_from_datavalue(tag, dv)

    async def write(self, tag: str, value: float, source_ts: float | None = None) -> None:
        """Escribe ``value`` con SourceTimestamp = ``source_ts`` (por defecto, ahora)."""
        from asyncua import ua

        spec = _SPECS[tag]
        node = self._node(tag)
        if spec.data_type == "Boolean":
            variant = ua.Variant(bool(value), ua.VariantType.Boolean)
        else:
            variant = ua.Variant(float(value), ua.VariantType.Double)
        stamp = time.time() if source_ts is None else source_ts
        await node.write_value(ua.DataValue(variant, SourceTimestamp=from_epoch(stamp)))

    async def subscribe(
        self,
        tags: list[str] | tuple[str, ...],
        handler: SampleHandler,
        publishing_interval_ms: float,
        every_update: bool = False,
    ) -> None:
        """Suscribe ``tags``; la suscripción se restablece sola tras una reconexión."""
        spec = _Subscription(tuple(tags), handler, publishing_interval_ms, every_update)
        self._subscriptions.append(spec)
        if self._client is not None:
            await self._create_subscription(spec)

    def _node(self, tag: str) -> Any:
        self._require()
        try:
            return self._nodes[tag]
        except KeyError:
            raise KeyError(f"Etiqueta desconocida: {tag}") from None

    async def _create_subscription(self, spec: _Subscription) -> None:
        from asyncua import ua

        client = self._client
        subscription = await client.create_subscription(
            spec.publishing_interval_ms, _Handler(self, spec)
        )
        trigger = (
            ua.DataChangeTrigger.StatusValueTimestamp
            if spec.every_update
            else ua.DataChangeTrigger.StatusValue
        )
        nodes = [self._nodes[tag] for tag in spec.tags]
        # API de bajo nivel de asyncua: permite fijar el filtro (disparador) y la cola sin límite.
        results = await subscription._subscribe(  # noqa: SLF001
            nodes, mfilter=ua.DataChangeFilter(Trigger=trigger), queuesize=0
        )
        for tag, result in zip(spec.tags, results, strict=True):
            if isinstance(result, ua.StatusCode):
                result.check()
                raise RuntimeError(f"No se pudo suscribir {tag}")

    # ------------------------------------------------------------------ reconexión
    async def run_with_reconnect(self, stop: asyncio.Event | None = None) -> None:
        """Mantiene la sesión viva y reconecta con espera exponencial (≤ 5 s, RNF-07)."""
        stop = stop or asyncio.Event()
        while not stop.is_set():
            await _wait(stop, 0.25)
            if stop.is_set() or self._closing:
                return
            try:
                await self._require().check_connection()
            except Exception as exc:
                await self._reconnect(exc, stop)

    async def _reconnect(self, cause: Exception, stop: asyncio.Event) -> None:
        lost_at = time.perf_counter()
        self.logger.warning(
            "Sesión con %s perdida (%s); reconectando", self.endpoint, cause.__class__.__name__
        )
        await self._drop_client(timeout_s=1.0)  # la sesión ya está caída: no esperar de más
        delay = self.initial_delay_s
        while not stop.is_set() and not self._closing:
            try:
                await self.connect()
            except Exception as exc:
                self.logger.info(
                    "Reintento fallido (%s); próximo en %.1f s", exc.__class__.__name__, delay
                )
                await _wait(stop, delay)
                delay = min(delay * 2, self.max_delay_s)
                continue
            recovery = time.perf_counter() - lost_at
            self.reconnections += 1
            self.recovery_times_s.append(recovery)
            self.logger.warning("Reconectado a %s en %.2f s", self.endpoint, recovery)
            return


async def _wait(stop: asyncio.Event, timeout_s: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=timeout_s)
