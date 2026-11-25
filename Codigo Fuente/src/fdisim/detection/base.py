"""Interfaz común de detectores y registro (RF-36, RF-38, RF-40, RNF-16).

El mismo objeto ``Detector`` procesa el flujo en línea (monitor OPC UA) y los datasets
almacenados (modo offline), lo que garantiza resultados equivalentes (RF-38).

``AlarmTracker`` convierte la señal de alarma con retención de cada detector en eventos de
alarma (RF-36): abre una alarma en el flanco de subida, la actualiza mientras dura (variables
implicadas, severidad e identificación) y la cierra en el flanco de bajada.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from fdisim.common.types import Alarm, AlarmKind, AlarmState, DetectorKind


@dataclass(slots=True)
class DetectionResult:
    t: float
    scores: dict[str, float]  # puntuación normalizada por variable o regla
    alarms: list[Alarm] = field(default_factory=list)  # alarmas abiertas o cerradas en t
    suspected_tag: str | None = None  # identificación (RF-37)
    processing_time_s: float | None = None  # RF-42
    alarm: bool = False  # estado de alarma (con retención) tras procesar la muestra
    triggered: tuple[str, ...] = ()  # reglas o residuos que superaron su límite en t


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

    def to_dict(self) -> dict[str, Any]:
        """Calibración serializable (JSON); la recarga ``from_dict``."""
        raise NotImplementedError


class AlarmTracker:
    """Eventos de alarma de un detector a partir de su señal con retención (RF-36)."""

    def __init__(self, detector: DetectorKind, prefix: str) -> None:
        self.detector = detector
        self.prefix = prefix
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.active: Alarm | None = None
        self.history: list[Alarm] = []

    def update(
        self,
        t: float,
        latched: bool,
        *,
        kind: AlarmKind | None = None,
        variables: Iterable[str] = (),
        score: float = 0.0,
        suspected: str | None = None,
    ) -> list[Alarm]:
        """Devuelve las alarmas que se abrieron o cerraron en ``t``."""
        changed: list[Alarm] = []
        if latched and self.active is None:
            self.count += 1
            self.active = Alarm(
                alarm_id=f"{self.prefix}{self.count:03d}",
                t=t,
                detector=self.detector,
                kind=kind or AlarmKind.RESIDUAL,
                variables=tuple(sorted(set(variables))),
                score=float(score),
                suspected_tag=suspected,
            )
            self.history.append(self.active)
            changed.append(self.active)
        elif latched and self.active is not None:
            alarm = self.active
            alarm.variables = tuple(sorted(set(alarm.variables) | set(variables)))
            alarm.score = max(alarm.score, float(score))
            if suspected is not None:
                alarm.suspected_tag = suspected
        elif not latched and self.active is not None:
            alarm = self.active
            alarm.state = AlarmState.CLOSED
            alarm.t_end = t
            self.active = None
            changed.append(alarm)
        return changed


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
