"""Motor de inyección FDI instalado en el gateway comprometido (RF-16).

Para cada valor que llega de la planta: ``observe`` en todas las estrategias, aplicar la
estrategia activa (si existe) y el filtro de sigilo, y devolver el valor a publicar.
Conserva el tipo de dato, el StatusCode Good y unas marcas de tiempo coherentes, de modo que
la falsificación es válida en el protocolo aunque el canal sea SignAndEncrypt.

En modo offline, la misma clase se aplica entre la planta simulada y los detectores (RF-38).

Fase de implementación: Fase 4.
"""

from __future__ import annotations

from fdisim.attacks.scheduler import AttackScheduler
from fdisim.common.bus import ExperimentBus


class FdiInjector:
    def __init__(self, scheduler: AttackScheduler, bus: ExperimentBus | None = None) -> None:
        self.scheduler = scheduler
        self.bus = bus

    def process(self, tag: str, value: float, sim_time: float) -> float:
        """Devuelve el valor que publicará el gateway (legítimo o falsificado)."""
        raise NotImplementedError("Fase 4 — RF-16: motor de inyección")
