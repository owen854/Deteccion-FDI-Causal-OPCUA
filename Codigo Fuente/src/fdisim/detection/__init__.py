"""M7–M8 — Detección: detector causal y método base de umbrales (RF-33 a RF-40).

Importar este paquete registra los detectores disponibles en ``detection.base``.
"""

from fdisim.detection import causal_detector, threshold_detector  # noqa: F401  (registro)
from fdisim.detection.base import DetectionResult, Detector, create_detector, registered_detectors

__all__ = ["DetectionResult", "Detector", "create_detector", "registered_detectors"]
