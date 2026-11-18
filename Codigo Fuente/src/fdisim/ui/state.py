"""Estado compartido de la HMI: buffers circulares de tendencias, alarmas y estado OPC UA.

Lo actualizan el monitor en línea y el orquestador; lo leen las páginas en cada refresco
(``ui.refresh_hz``). Se mantiene acotado para cumplir RNF-05 (memoria).

Fase de implementación: Fase 7.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from fdisim.common.types import Alarm


@dataclass(slots=True)
class UiState:
    max_points: int = 3600
    trends: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    scores: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    alarms: deque[Alarm] = field(default_factory=lambda: deque(maxlen=500))
    connection_status: dict[str, str] = field(default_factory=dict)
    running_scenario: str | None = None

    def push_trend(self, tag: str, t: float, value: float) -> None:
        buf = self.trends.setdefault(tag, deque(maxlen=self.max_points))
        buf.append((t, value))
