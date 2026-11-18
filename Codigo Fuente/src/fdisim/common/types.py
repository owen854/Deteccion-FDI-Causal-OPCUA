"""Contratos de datos compartidos entre componentes (Documento 03, §4.1).

Estos tipos son la interfaz estable entre módulos desarrollados en paralelo (riesgo R8).
Cambiarlos exige acuerdo del equipo y actualizar las pruebas de ``tests/``.

Requerimientos: RF-14, RF-21, RF-25, RF-26, RF-36.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Etiquetas de instrumentación (ISA-5.1) — ERS §5
# ---------------------------------------------------------------------------
LT_101 = "LT-101"  # nivel del tanque 1 (h1) [cm]
LT_102 = "LT-102"  # nivel del tanque 2 (h2) [cm] — variable controlada
FT_101 = "FT-101"  # caudal de entrada (q_in) [cm³/s]
FT_102 = "FT-102"  # caudal de salida del tanque 2 (opcional) [cm³/s]
P_101 = "P-101"  # comando de la bomba (u) [%]
SP_102 = "LIC-102.SP"  # consigna de nivel del tanque 2 [cm]

PROCESS_TAGS: tuple[str, ...] = (LT_101, LT_102, FT_101, P_101, SP_102)
"""Variables del proceso que viajan por OPC UA y analiza el detector."""

SYMBOLS: Mapping[str, str] = {
    LT_101: "h1",
    LT_102: "h2",
    FT_101: "q_in",
    FT_102: "q2",
    P_101: "u",
    SP_102: "SP",
}


class AttackType(StrEnum):
    """Tipos de ataque FDI (RF-17 a RF-19)."""

    BIAS = "bias"
    RAMP = "ramp"
    REPLAY = "replay"


class DetectorKind(StrEnum):
    """Detectores comparados en el OE4."""

    CAUSAL = "causal"
    THRESHOLD = "threshold"


class AlarmKind(StrEnum):
    """Tipo de inconsistencia que originó una alarma (RF-36)."""

    RESIDUAL = "residual"
    CUSUM = "cusum"
    EWMA = "ewma"
    STRUCTURAL = "structural"
    LIMIT = "limit"
    STATISTICAL = "statistical"


class AlarmState(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class RunMode(StrEnum):
    """Modo de ejecución (RF-38, RF-43)."""

    NETWORK = "network"  # co-simulación con OPC UA real
    OFFLINE = "offline"  # simulación numérica rápida, sin red


@dataclass(frozen=True, slots=True)
class Sample:
    """Valor de una variable tal como lo recibe un cliente OPC UA (RF-14)."""

    tag: str
    value: float
    source_ts: float  # SourceTimestamp (s, época Unix)
    server_ts: float  # ServerTimestamp
    received_ts: float  # instante de recepción en el cliente
    status: str = "Good"


@dataclass(frozen=True, slots=True)
class GroundTruthRecord:
    """Verdad de terreno de un paso de simulación (RF-06). Viaja por el plano de experimento."""

    sim_time: float
    true_values: Mapping[str, float]
    measured_values: Mapping[str, float]
    attack_active: bool = False
    attack_id: str | None = None


@dataclass(frozen=True, slots=True)
class StealthSpec:
    """Restricciones de sigilo de un ataque (RF-20)."""

    enabled: bool = True
    envelope: tuple[float, float] | None = None
    max_rate_per_s: float | None = None


@dataclass(frozen=True, slots=True)
class AttackSpec:
    """Definición declarativa de un ataque, leída del escenario YAML (RF-20)."""

    attack_id: str
    type: AttackType
    targets: tuple[str, ...]
    start_s: float
    duration_s: float
    params: Mapping[str, float] = field(default_factory=dict)
    stealth: StealthSpec = field(default_factory=StealthSpec)

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    def is_active(self, t: float) -> bool:
        """True si el instante ``t`` (tiempo simulado) cae en la ventana de ataque."""
        return self.start_s <= t < self.end_s


@dataclass(frozen=True, slots=True)
class AttackEvent:
    """Intervalo de ataque efectivamente ejecutado; es la etiqueta de evaluación (RF-21)."""

    attack_id: str
    type: AttackType
    targets: tuple[str, ...]
    t_start: float
    t_end: float | None
    params: Mapping[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Alarm:
    """Alarma emitida por un detector (RF-36)."""

    alarm_id: str
    t: float
    detector: DetectorKind
    kind: AlarmKind
    variables: tuple[str, ...]
    score: float
    suspected_tag: str | None = None  # identificación (RF-37)
    state: AlarmState = AlarmState.ACTIVE


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Metadatos de reproducibilidad de una corrida (RF-26, RNF-08)."""

    run_id: str
    scenario: str
    seed: int
    mode: RunMode
    started_at: str  # ISO 8601
    git_commit: str | None
    config_sha256: str
    package_versions: Mapping[str, str] = field(default_factory=dict)
    files_sha256: Mapping[str, str] = field(default_factory=dict)
