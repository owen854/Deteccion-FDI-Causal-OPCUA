"""Detector de inconsistencias causales (RF-33 a RF-37; OE3).

Flujo por muestra: residuos (un paso y multi-paso) → reglas de decisión (umbral, CUSUM,
EWMA) → verificación estructural por ventanas → identificación → alarmas con retención.

Fase de implementación: Fase 6.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdisim.common.types import DetectorKind
from fdisim.detection.base import DetectionResult, Detector, register_detector


@register_detector(DetectorKind.CAUSAL)
class CausalDetector(Detector):
    def __init__(
        self, model_dir: str | None = None, config: Mapping[str, Any] | None = None
    ) -> None:
        self.model_dir = model_dir
        self.config = dict(config or {})

    def fit(self, normal_data: Any) -> CausalDetector:
        raise NotImplementedError("Fase 6 — RF-34: calibración del detector causal")

    def update(self, t: float, values: Mapping[str, float]) -> DetectionResult:
        raise NotImplementedError("Fase 6 — RF-33..RF-37: detección causal")
