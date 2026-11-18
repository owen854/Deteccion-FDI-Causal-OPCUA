"""Método base de umbrales (RF-40; OE4).

Alarma cuando una variable sale de (a) sus límites operativos estáticos o (b) los límites
estadísticos ``μ ± k·σ`` estimados en operación normal; regla opcional de tasa de cambio.
Se ejecuta en paralelo con el detector causal sobre exactamente las mismas muestras.

Fase de implementación: Fase 6.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdisim.common.types import DetectorKind
from fdisim.detection.base import DetectionResult, Detector, register_detector


@register_detector(DetectorKind.THRESHOLD)
class ThresholdDetector(Detector):
    def __init__(
        self,
        operating_limits: Mapping[str, tuple[float, float]] | None = None,
        k_sigma: float = 3.0,
        max_rate: Mapping[str, float] | None = None,
    ) -> None:
        self.operating_limits = dict(operating_limits or {})
        self.k_sigma = k_sigma
        self.max_rate = dict(max_rate or {})

    def fit(self, normal_data: Any) -> ThresholdDetector:
        raise NotImplementedError("Fase 6 — RF-40: estimación de μ y σ")

    def update(self, t: float, values: Mapping[str, float]) -> DetectionResult:
        raise NotImplementedError("Fase 6 — RF-40: método base de umbrales")
