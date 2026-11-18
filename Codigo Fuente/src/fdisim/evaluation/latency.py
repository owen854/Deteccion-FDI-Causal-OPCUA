"""Métricas temporales (RF-42; RNF-02, RNF-03).

- Latencia OPC UA por muestra: ``received_ts − source_ts`` (por salto y extremo a extremo).
- Tiempo de procesamiento del detector por muestra.
- Tiempo de respuesta: inicio del ataque → alarma visible en la HMI.

Resumen estadístico: media, mediana, p95 y máximo.
Fase de implementación: Fase 8 (la instrumentación se añade en las Fases 3 y 6).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdisim.common.types import Sample


@dataclass(frozen=True, slots=True)
class LatencySummary:
    mean: float
    median: float
    p95: float
    max: float
    n: int


def summarize(values: Sequence[float]) -> LatencySummary:
    raise NotImplementedError("Fase 8 — RF-42: resumen estadístico")


def opcua_latencies(samples: Sequence[Sample]) -> list[float]:
    raise NotImplementedError("Fase 8 — RF-42: latencia OPC UA")


def response_times(
    attack_starts: Sequence[float], ui_alarm_times: Sequence[float]
) -> list[float | None]:
    raise NotImplementedError("Fase 8 — RF-42: tiempo de respuesta extremo a extremo")
