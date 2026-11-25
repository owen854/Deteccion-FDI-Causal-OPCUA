"""Método base de umbrales (RF-40; OE4).

Alarma cuando una variable sale de (a) sus límites operativos estáticos o (b) los límites
estadísticos ``μ ± k·σ`` estimados en operación normal (entrenamiento); regla opcional de tasa
de cambio (``max_rate``, unidades por segundo). Usa la misma retención de alarmas que el
detector causal y se ejecuta en paralelo con él sobre exactamente las mismas muestras.

Como señala la variable que sale de sus límites, su «identificación» es esa variable; sirve de
referencia para la del detector causal (RF-37).

Implementado en la Fase 6.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, AlarmKind, DetectorKind
from fdisim.detection.base import AlarmTracker, DetectionResult, Detector, register_detector
from fdisim.detection.decision import AlarmLatch

BASELINE_TAGS: tuple[str, ...] = (LT_101, LT_102, FT_101, P_101)


@register_detector(DetectorKind.THRESHOLD)
class ThresholdDetector(Detector):
    def __init__(
        self,
        operating_limits: Mapping[str, Sequence[float]] | None = None,
        k_sigma: float = 3.0,
        max_rate: Mapping[str, float] | None = None,
        *,
        hold_s: float = 2.0,
        tags: Sequence[str] = BASELINE_TAGS,
        stats: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        self.operating_limits = {
            k: (float(v[0]), float(v[1])) for k, v in (operating_limits or {}).items()
        }
        self.k_sigma = float(k_sigma)
        self.max_rate = {k: float(v) for k, v in (max_rate or {}).items()}
        self.hold_s = float(hold_s)
        self.tags = tuple(tags)
        self.stats = {k: (float(v[0]), float(v[1])) for k, v in (stats or {}).items()}
        self.info: dict[str, Any] = {}
        self.latch = AlarmLatch(self.hold_s)
        self.tracker = AlarmTracker(DetectorKind.THRESHOLD, "B")
        self._prev: tuple[float, dict[str, float]] | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, Any], **kwargs: Any) -> ThresholdDetector:
        detection = config.get("detection", {})
        base = detection.get("threshold_baseline", {})
        return cls(
            base.get("operating_limits"),
            float(base.get("k_sigma", 3.0)),
            base.get("max_rate"),
            hold_s=float(detection.get("decision", {}).get("alarm_hold_s", 2.0)),
            **kwargs,
        )

    @property
    def calibrated(self) -> bool:
        return bool(self.stats)

    def reset(self) -> None:
        self.latch.reset()
        self.tracker.reset()
        self._prev = None

    def fit(self, normal_data: Any) -> ThresholdDetector:
        from fdisim.detection.causal_detector import split_normal_data

        train, _ = split_normal_data(normal_data)
        self.stats = {
            tag: (float(np.mean(train[tag])), float(np.std(train[tag], ddof=1)))
            for tag in self.tags
        }
        return self

    def update(self, t: float, values: Mapping[str, float]) -> DetectionResult:
        if not self.calibrated:
            raise RuntimeError("El método base no está calibrado (fit o calibración)")
        start = time.perf_counter()
        scores: dict[str, float] = {}
        triggered: list[str] = []
        best: tuple[float, AlarmKind, str | None] = (0.0, AlarmKind.STATISTICAL, None)
        dt = t - self._prev[0] if self._prev is not None else math.nan
        for tag in self.tags:
            x = float(values[tag])
            mean, std = self.stats[tag]
            ratio = abs(x - mean) / (self.k_sigma * std) if std > 0 else 0.0
            scores[tag] = (x - mean) / std if std > 0 else 0.0
            fired: list[tuple[float, AlarmKind]] = []
            if ratio > 1.0:
                fired.append((ratio, AlarmKind.STATISTICAL))
            limits = self.operating_limits.get(tag)
            if limits is not None and not limits[0] <= x <= limits[1]:
                fired.append((max(ratio, 1.0) + 1.0, AlarmKind.LIMIT))
            rate_limit = self.max_rate.get(tag)
            if rate_limit and self._prev is not None and dt > 0:
                rate = abs(x - self._prev[1][tag]) / dt
                scores[f"rate:{tag}"] = rate / rate_limit
                if rate > rate_limit:
                    fired.append((rate / rate_limit, AlarmKind.STATISTICAL))
            if fired:
                triggered.append(tag)
                top = max(fired, key=lambda item: item[0])
                if top[0] > best[0]:
                    best = (top[0], top[1], tag)
        self._prev = (t, {tag: float(values[tag]) for tag in self.tags})
        scores["max"] = max(
            abs(scores[tag]) / self.k_sigma for tag in self.tags if math.isfinite(scores[tag])
        )
        latched = self.latch.update(t, bool(triggered))
        alarms = self.tracker.update(
            t, latched, kind=best[1], variables=triggered, score=best[0], suspected=best[2]
        )
        active = self.tracker.active
        suspected = active.suspected_tag if active is not None else None
        return DetectionResult(
            t=t,
            scores=scores,
            alarms=alarms,
            suspected_tag=suspected,
            processing_time_s=time.perf_counter() - start,
            alarm=latched,
            triggered=tuple(triggered),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "k_sigma": self.k_sigma,
            "operating_limits": {k: list(v) for k, v in self.operating_limits.items()},
            "max_rate": self.max_rate,
            "hold_s": self.hold_s,
            "tags": list(self.tags),
            "stats": {k: list(v) for k, v in self.stats.items()},
            "info": self.info,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ThresholdDetector:
        detector = cls(
            data.get("operating_limits"),
            float(data.get("k_sigma", 3.0)),
            data.get("max_rate"),
            hold_s=float(data.get("hold_s", 2.0)),
            tags=data.get("tags", BASELINE_TAGS),
            stats=data.get("stats"),
        )
        detector.info = dict(data.get("info", {}))
        return detector
