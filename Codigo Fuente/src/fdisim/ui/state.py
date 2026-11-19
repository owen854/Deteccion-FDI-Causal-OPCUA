"""Estado compartido de la HMI: últimos valores, tendencias, alarmas y estado OPC UA.

Lo actualiza el enlace OPC UA de la HMI (``ui.link``) y, desde la Fase 6, el monitor en línea;
lo leen las páginas en cada refresco (``ui.refresh_hz``). Las tendencias se guardan
submuestreadas (un punto cada ``trend_step_s`` por variable) y en búferes circulares, para
cumplir RNF-05 (memoria acotada) y no saturar el navegador.

Implementado en la Fase 3 (HMI v0); se amplía en la Fase 7.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from fdisim.common.types import SP_102, Alarm, Sample

CLOCK_TAG = "SIM.TIME"  # se publica en cada paso
HOLD_TAGS = (SP_102,)


@dataclass(slots=True)
class UiState:
    max_points: int = 1200  # 10 min con un punto cada 0,5 s
    trend_step_s: float = 0.5
    trends: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    scores: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    alarms: deque[Alarm] = field(default_factory=lambda: deque(maxlen=500))
    latest: dict[str, Sample] = field(default_factory=dict)
    connection_status: dict[str, str] = field(default_factory=dict)
    running_scenario: str | None = None
    messages: deque[str] = field(default_factory=lambda: deque(maxlen=50))

    def push_trend(self, tag: str, t: float, value: float) -> None:
        buf = self.trends.setdefault(tag, deque(maxlen=self.max_points))
        if buf and t - buf[-1][0] < self.trend_step_s:
            return
        buf.append((t, value))

    def push_sample(self, sample: Sample) -> None:
        """Registra una muestra OPC UA (último valor y, si es numérica, su tendencia).

        Las variables que solo cambian por escritura (consigna) se repiten en cada paso del
        tiempo simulado, para que su tendencia se dibuje como una línea continua.
        """
        self.latest[sample.tag] = sample
        if sample.status == "Good":
            self.push_trend(sample.tag, sample.source_ts, sample.value)
        if sample.tag == CLOCK_TAG:
            for tag in HOLD_TAGS:
                held = self.latest.get(tag)
                if held is not None and held.status == "Good":
                    self.push_trend(tag, sample.source_ts, held.value)

    def value(self, tag: str, default: float = float("nan")) -> float:
        sample = self.latest.get(tag)
        return sample.value if sample is not None else default
