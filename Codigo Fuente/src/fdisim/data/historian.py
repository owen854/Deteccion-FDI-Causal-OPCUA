"""Historiador de series de tiempo (RF-25).

Acumula en memoria (con volcado periódico a disco) las muestras OPC UA recibidas, la verdad
de terreno, los eventos de ataque y las salidas de los detectores, cada uno en su tabla:
``samples``, ``ground_truth``, ``attacks``, ``detections`` y ``alarms``.

Fase de implementación: Fase 3. Dependencias previstas: pandas, pyarrow.
"""

from __future__ import annotations

from pathlib import Path

from fdisim.common.types import Alarm, AttackEvent, GroundTruthRecord, Sample


class Historian:
    def __init__(self, run_dir: Path, flush_every: int = 1000) -> None:
        self.run_dir = run_dir
        self.flush_every = flush_every

    def record_sample(self, sample: Sample) -> None:
        raise NotImplementedError("Fase 3 — RF-25: historiador")

    def record_ground_truth(self, record: GroundTruthRecord) -> None:
        raise NotImplementedError("Fase 3 — RF-25")

    def record_attack(self, event: AttackEvent) -> None:
        raise NotImplementedError("Fase 4 — RF-25")

    def record_detection(self, t: float, detector: str, scores: dict[str, float]) -> None:
        raise NotImplementedError("Fase 6 — RF-25")

    def record_alarm(self, alarm: Alarm) -> None:
        raise NotImplementedError("Fase 6 — RF-25")

    def flush(self) -> None:
        raise NotImplementedError("Fase 3 — RF-25")
