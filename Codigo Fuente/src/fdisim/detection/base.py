"""Interfaz común de detectores y registro (RF-38, RF-40, RNF-16).

El mismo objeto ``Detector`` procesa el flujo en línea (monitor OPC UA) y los datasets
almacenados (modo offline), lo que garantiza resultados equivalentes (RF-38).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from fdisim.common.types import Alarm, DetectorKind


@dataclass(slots=True)
class DetectionResult:
    t: float
    scores: dict[str, float]  # puntuación normalizada por variable o regla
    alarms: list[Alarm] = field(default_factory=list)
    suspected_tag: str | None = None  # identificación (RF-37)
    processing_time_s: float | None = None  # RF-42


class Detector(ABC):
    kind: ClassVar[DetectorKind]

    @abstractmethod
    def fit(self, normal_data: Any) -> Detector:
        """Calibra el detector con datos de operación normal (entrenamiento y validación)."""

    @abstractmethod
    def update(self, t: float, values: Mapping[str, float]) -> DetectionResult:
        """Procesa una muestra alineada ``{tag: valor}`` en el instante ``t``."""

    def reset(self) -> None:  # noqa: B027
        """Reinicia el estado interno (acumuladores, ventanas). Por defecto no hace nada."""


_D = TypeVar("_D", bound=type[Detector])
_REGISTRY: dict[DetectorKind, type[Detector]] = {}


def register_detector(kind: DetectorKind) -> Callable[[_D], _D]:
    def decorator(cls: _D) -> _D:
        if kind in _REGISTRY:
            raise ValueError(f"Detector ya registrado: {kind.value}")
        cls.kind = kind
        _REGISTRY[kind] = cls
        return cls

    return decorator


def create_detector(kind: DetectorKind, **kwargs: Any) -> Detector:
    try:
        cls = _REGISTRY[kind]
    except KeyError:
        raise ValueError(f"Detector no registrado: {kind}") from None
    return cls(**kwargs)


def registered_detectors() -> tuple[DetectorKind, ...]:
    return tuple(_REGISTRY)
