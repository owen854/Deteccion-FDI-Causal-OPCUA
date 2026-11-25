"""Monitor OPC UA en línea: cliente de supervisión que alimenta a los detectores (RF-25, RF-38).

Se suscribe a las variables del gateway (mismo canal que el controlador) con una notificación
por paso publicado y registra cada muestra en el historiador con sus tres marcas de tiempo y
su StatusCode (RF-14, RF-25). Es la «vista del supervisor»: el detector solo ve lo que llega
por OPC UA.

Desde la Fase 6, si hay detectores:

- ``GridAligner`` lleva las muestras a la rejilla ``detection.period_s`` con retención de orden
  cero, con las mismas reglas que ``data.dataset.align_samples`` (tiempo simulado derivado del
  SourceTimestamp y de SIM.TIME, inicio en t ≥ 0, solo valores ``Good``). Por eso reprocesar
  la corrida guardada reproduce las alarmas en línea (RF-38).
- En cada instante de la rejilla ejecuta en paralelo el detector causal y el método base,
  mide el tiempo de procesamiento (RF-42), guarda las salidas y las alarmas en el historiador
  (RF-25, RF-36) y las entrega a ``on_result`` (el componente las publica en el plano de
  experimento para la HMI, RF-49).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from fdisim.common.types import FT_101, LT_101, LT_102, PROCESS_TAGS, Sample
from fdisim.data.historian import Historian
from fdisim.detection.base import DetectionResult, Detector
from fdisim.opcua.client_base import OpcUaClient

CLOCK_TAG = "SIM.TIME"
CLOCKED_TAGS = (LT_101, LT_102, FT_101)  # la planta las publica en cada paso


class GridAligner:
    """Alinea muestras asíncronas en la rejilla de detección, como ``align_samples``.

    Las mediciones (``clocked``) llegan en cada paso de la planta; la orden de la bomba y la
    consigna, solo cuando un cliente las escribe. Un instante T de la rejilla se emite cuando
    todas las mediciones ya tienen un valor posterior a T (llegó el paso siguiente), de modo
    que cualquier escritura con tiempo ≤ T ya se recibió; cada variable toma su último valor
    con tiempo ≤ T (retención de orden cero).
    """

    def __init__(
        self,
        period_s: float,
        tags: Sequence[str],
        time_scale: float = 1.0,
        clocked: Sequence[str] = CLOCKED_TAGS,
    ) -> None:
        self.period_s = float(period_s)
        self.tags = tuple(tags)
        self.clocked = tuple(tag for tag in self.tags if tag in clocked) or self.tags
        self.time_scale = float(time_scale)
        self._ref: tuple[float, float] | None = None
        self._pending: list[tuple[str, float, float]] = []
        self._series: dict[str, deque[tuple[float, float]]] = {tag: deque() for tag in self.tags}
        self._next: float | None = None

    def on_clock(self, sim_time: float, source_ts: float) -> list[tuple[float, dict[str, float]]]:
        """Un SIM.TIME con t > 0 fija la referencia entre SourceTimestamp y tiempo simulado."""
        if self._ref is not None or sim_time <= 0 or not math.isfinite(source_ts):
            return []
        self._ref = (sim_time, source_ts)
        pending, self._pending = self._pending, []
        out: list[tuple[float, dict[str, float]]] = []
        for tag, ts, value in pending:
            out.extend(self.push(tag, ts, value))
        return out

    def sim_time_of(self, source_ts: float) -> float:
        assert self._ref is not None
        t_ref, s_ref = self._ref
        return round(t_ref + (source_ts - s_ref) * self.time_scale, 3)

    def push(
        self, tag: str, source_ts: float, value: float, status: str = "Good"
    ) -> list[tuple[float, dict[str, float]]]:
        """Agrega una muestra y devuelve los instantes de la rejilla que quedaron completos."""
        if tag not in self._series or status != "Good":
            return []
        if self._ref is None:
            self._pending.append((tag, source_ts, value))
            return []
        series = self._series[tag]
        t = self.sim_time_of(source_ts)
        if series and t < series[-1][0]:
            return []  # notificación atrasada: la rejilla ya avanzó
        series.append((t, float(value)))
        return self._emit()

    def _emit(self) -> list[tuple[float, dict[str, float]]]:
        if any(not s for s in self._series.values()):
            return []
        if self._next is None:
            first = max(s[0][0] for s in self._series.values())
            self._next = round(max(0.0, math.ceil(first / self.period_s - 1e-9) * self.period_s), 6)
        out = []
        while all(self._series[tag][-1][0] > self._next + 1e-9 for tag in self.clocked):
            values = {}
            for tag, series in self._series.items():
                # Último valor con sim_time ≤ instante de la rejilla; se descarta lo anterior.
                while len(series) > 1 and series[1][0] <= self._next + 1e-9:
                    series.popleft()
                values[tag] = series[0][1]
            out.append((self._next, values))
            self._next = round(self._next + self.period_s, 6)
        return out


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
        time_scale: float = 1.0,
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
        self.processed = 0
        self.alarms = 0
        self.processing_ms: deque[float] = deque(maxlen=20000)
        self.aligner = GridAligner(period_s, tags, time_scale)
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.client.connect_with_retry()
        subscribed = (*self.tags, CLOCK_TAG) if self.detectors else self.tags
        await self.client.subscribe(
            subscribed, self._on_sample, self.publishing_interval_ms, every_update=True
        )
        self.logger.info(
            "Monitor suscrito a %s en %s (%s)",
            ", ".join(self.tags),
            self.client.endpoint,
            "detectores: " + ", ".join(d.kind.value for d in self.detectors)
            if self.detectors
            else "solo registro",
        )

    async def run(self) -> None:
        if not self.client.connected:
            await self.start()
        await self.client.run_with_reconnect(self._stop)

    async def stop(self) -> None:
        self._stop.set()
        await self.client.disconnect()
        self.historian.close()
        self.logger.info(
            "Monitor detenido: %d muestras registradas, %d instantes analizados, %d alarmas",
            self.received,
            self.processed,
            self.alarms,
        )

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "samples": self.received,
            "reconnections": self.client.reconnections,
            "recovery_s": list(self.client.recovery_times_s),
        }
        if self.detectors:
            times = sorted(self.processing_ms)
            out["detection"] = {
                "instants": self.processed,
                "alarms": self.alarms,
                "processing_p95_ms": times[int(0.95 * (len(times) - 1))] if times else None,
            }
        return out

    def _on_sample(self, sample: Sample) -> None:
        if sample.tag == CLOCK_TAG:
            ready = self.aligner.on_clock(sample.value, sample.source_ts)
        else:
            self.historian.record_sample(sample)
            self.received += 1
            if not self.detectors:
                return
            ready = self.aligner.push(sample.tag, sample.source_ts, sample.value, sample.status)
        for t, values in ready:
            self._analyze(t, values)

    def _analyze(self, t: float, values: dict[str, float]) -> None:
        self.processed += 1
        for detector in self.detectors:
            try:
                result = detector.update(t, values)
            except Exception:  # un fallo del detector no debe tumbar el registro
                self.logger.exception("Fallo del detector %s en t = %.1f s", detector.kind.value, t)
                continue
            kind = detector.kind.value
            ms = 1000.0 * (result.processing_time_s or 0.0)
            self.processing_ms.append(ms)
            self.historian.record_detection(
                t,
                kind,
                result.scores,
                alarm=result.alarm,
                suspected=result.suspected_tag,
                triggered=result.triggered,
                processing_ms=ms,
            )
            for alarm in result.alarms:
                self.historian.record_alarm(alarm)
                if alarm.t_end is None:
                    self.alarms += 1
                    self.logger.warning(
                        "Alarma %s (%s, %s) en t = %.1f s: %s; variable sospechosa %s",
                        alarm.alarm_id,
                        kind,
                        alarm.kind.value,
                        alarm.t,
                        ", ".join(alarm.variables) or "—",
                        alarm.suspected_tag or "—",
                    )
            if self.on_result is not None:
                self.on_result(kind, result)
