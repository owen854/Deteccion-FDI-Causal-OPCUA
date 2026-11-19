"""Gateway OPC UA agregador — nodo intermedio comprometible (RF-13, RF-16).

Es a la vez cliente del servidor de planta y servidor para el controlador, el monitor y la HMI
(``opc.tcp://127.0.0.1:4841/fdisim/gateway``). Expone el mismo modelo de información que la
planta (comprueba al arrancar que la planta publica todas las etiquetas) y retransmite:

- **Planta → clientes:** se suscribe a todas las variables con el disparador
  StatusValueTimestamp (una notificación por paso) y reescribe cada valor en su propio
  espacio de direcciones **conservando el SourceTimestamp** original. Una sola tarea consume
  la cola de notificaciones, así que el orden se preserva.
- **Clientes → planta:** las escrituras de los clientes sobre P-101 y LIC-102.SP se detectan
  con la retrollamada PostWrite de asyncua y se reenvían a la planta en orden.

Cada valor de proceso pasa por el ``FdiInjector`` antes de publicarse. Sin inyector (Fase 3)
el gateway es transparente. Con ataque (Fase 4), los clientes reciben datos falsos firmados y
cifrados con las credenciales legítimas del gateway (Informe OE1 §3.6).

Registra la latencia añadida por el salto (recepción → republicación) y la del salto
planta → gateway (SourceTimestamp → recepción) (criterio de RF-13).

Implementado en la Fase 3 (modo transparente); la inyección llega en la Fase 4.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from typing import Any

import numpy as np

from fdisim.attacks.injector import FdiInjector
from fdisim.common.bus import ExperimentBus
from fdisim.common.types import P_101, PROCESS_TAGS, SP_102, Sample
from fdisim.opcua.client_base import OpcUaClient, from_epoch, to_epoch
from fdisim.opcua.plant_server import SIM_RUNNING, SIM_TIME
from fdisim.opcua.security import SecurityConfig

COMPONENT = "gateway"
RELAYED_TAGS: tuple[str, ...] = (*PROCESS_TAGS, SIM_TIME, SIM_RUNNING)
WRITABLE_TAGS = frozenset({P_101, SP_102})
_MAX_LATENCY_SAMPLES = 200_000


class AggregatingGateway:
    def __init__(
        self,
        endpoint: str,
        upstream: OpcUaClient,
        injector: FdiInjector | None,
        security: SecurityConfig,
        bus: ExperimentBus,
        publishing_interval_ms: float = 100.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.upstream = upstream
        self.injector = injector
        self.security = security
        self.bus = bus
        self.publishing_interval_ms = publishing_interval_ms
        self.logger = logger or logging.getLogger("fdisim.gateway")
        self.sim_time = 0.0
        self.relayed = 0
        self.forwarded_writes = 0
        self.failed_writes = 0
        self._server: Any = None
        self._nodes: dict[str, Any] = {}
        self._tag_by_nodeid: dict[Any, str] = {}
        self._downstream: asyncio.Queue[Sample] = asyncio.Queue()
        self._upstream_writes: asyncio.Queue[tuple[str, float, float | None]] = asyncio.Queue()
        self._hop_ms: list[float] = []
        self._added_ms: list[float] = []
        self._seen: set[str] = set()

    async def start(self) -> None:
        """Levanta el servidor del gateway, conecta con la planta y replica sus valores."""
        from asyncua.common.callback import CallbackType

        from fdisim.opcua.factory import create_server

        self._server, self._nodes = await create_server(self.endpoint, self.security, COMPONENT)
        self._tag_by_nodeid = {node.nodeid: tag for tag, node in self._nodes.items()}
        self._server.subscribe_server_callback(CallbackType.PostWrite, self._on_client_write)
        await self._server.start()

        await self.upstream.connect_with_retry()
        missing = set(RELAYED_TAGS) - set(await self.upstream.browse_tags())
        if missing:
            raise RuntimeError(f"La planta no publica las etiquetas {sorted(missing)}")
        for tag in RELAYED_TAGS:
            await self._publish(await self.upstream.read(tag))
        await self.upstream.subscribe(
            RELAYED_TAGS, self._downstream.put_nowait, self.publishing_interval_ms, True
        )
        self.logger.info(
            "Gateway en %s replicando %d variables de %s (modo %s)",
            self.endpoint,
            len(RELAYED_TAGS),
            self.upstream.endpoint,
            "transparente" if self.injector is None else "con inyector",
        )

    async def relay_forever(self, stop: asyncio.Event | None = None) -> None:
        """Retransmite planta → clientes (vía inyector) y clientes → planta hasta ``stop``."""
        stop = stop or asyncio.Event()
        tasks = [
            asyncio.create_task(self._relay_downstream()),
            asyncio.create_task(self._relay_upstream()),
            asyncio.create_task(self.upstream.run_with_reconnect(stop)),
        ]
        try:
            await stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def stop(self) -> None:
        await self.upstream.disconnect()
        if self._server is not None:
            await self._server.stop()
            self._server = None

    def stats(self) -> dict[str, Any]:
        return {
            "relayed": self.relayed,
            "forwarded_writes": self.forwarded_writes,
            "failed_writes": self.failed_writes,
            "reconnections": self.upstream.reconnections,
            "recovery_s": list(self.upstream.recovery_times_s),
            "hop_plant_to_gateway_ms": _percentiles(self._hop_ms),
            "added_by_gateway_ms": _percentiles(self._added_ms),
        }

    # ------------------------------------------------------------------ retransmisión
    async def _relay_downstream(self) -> None:
        while True:
            sample = await self._downstream.get()
            try:
                await self._publish(sample)
            except Exception:
                self.logger.exception("No se pudo republicar %s", sample.tag)
                continue
            self.relayed += 1
            # La primera notificación de cada variable trae su último valor, con una marca de
            # tiempo anterior a la suscripción: no representa la latencia del enlace.
            first = sample.tag not in self._seen
            self._seen.add(sample.tag)
            if not first and len(self._added_ms) < _MAX_LATENCY_SAMPLES:
                self._hop_ms.append(1000.0 * (sample.received_ts - sample.source_ts))
                self._added_ms.append(1000.0 * (time.time() - sample.received_ts))

    async def _relay_upstream(self) -> None:
        while True:
            tag, value, source_ts = await self._upstream_writes.get()
            try:
                await self.upstream.write(tag, value, source_ts)
                self.forwarded_writes += 1
            except Exception as exc:
                self.failed_writes += 1
                self.logger.warning(
                    "No se pudo reenviar %s = %.3f a la planta: %s", tag, value, exc
                )

    async def _publish(self, sample: Sample) -> None:
        from asyncua import ua

        value: float | bool = sample.value
        if sample.tag == SIM_TIME:
            self.sim_time = sample.value
        if self.injector is not None and sample.tag in PROCESS_TAGS:
            value = self.injector.process(sample.tag, sample.value, self.sim_time)
        variant = (
            ua.Variant(bool(value), ua.VariantType.Boolean)
            if sample.tag == SIM_RUNNING
            else ua.Variant(float(value), ua.VariantType.Double)
        )
        dv = ua.DataValue(
            variant,
            SourceTimestamp=from_epoch(sample.source_ts),
            ServerTimestamp=from_epoch(time.time()),
        )
        await self._server.write_attribute_value(self._nodes[sample.tag].nodeid, dv)

    def _on_client_write(self, event: Any, dispatcher: Any) -> None:
        """PostWrite: reenvía a la planta las escrituras aceptadas sobre P-101 y la consigna."""
        from asyncua import ua

        for item, status in zip(
            event.request_params.NodesToWrite, event.response_params, strict=False
        ):
            tag = self._tag_by_nodeid.get(item.NodeId)
            if (
                tag in WRITABLE_TAGS
                and item.AttributeId == ua.AttributeIds.Value
                and status.is_good()
            ):
                stamp = to_epoch(item.Value.SourceTimestamp)
                self._upstream_writes.put_nowait(
                    (tag, float(item.Value.Value.Value), stamp if math.isfinite(stamp) else None)
                )


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    arr = np.asarray(values)
    return {
        "n": int(arr.size),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(arr.max()),
    }
