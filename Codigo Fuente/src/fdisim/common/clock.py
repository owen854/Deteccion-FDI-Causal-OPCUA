"""Reloj de co-simulación de paso fijo (RF-05).

Sincroniza el tiempo simulado con el reloj de pared mediante un factor de escala:
``t_pared = t_sim / time_scale``. Registra los pasos atrasados (overruns) para verificar
RNF-01 y la desviación acumulada (< 1 % en corridas de 10 min).

Fase de implementación: Fase 3.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ClockStats:
    steps: int = 0
    overruns: int = 0
    max_lag_s: float = 0.0


class CoSimClock:
    """Reloj asíncrono de paso fijo.

    Uso previsto::

        clock = CoSimClock(dt_s=0.1, time_scale=1.0)
        async for t_sim in clock.ticks(duration_s=1800):
            plant.step(...)
    """

    def __init__(self, dt_s: float, time_scale: float = 1.0) -> None:
        if dt_s <= 0 or time_scale <= 0:
            raise ValueError("dt_s y time_scale deben ser positivos")
        self.dt_s = dt_s
        self.time_scale = time_scale
        self.stats = ClockStats()

    @property
    def sim_time(self) -> float:
        """Tiempo simulado actual [s]."""
        raise NotImplementedError("Fase 3 — RF-05: reloj de co-simulación")

    async def ticks(self, duration_s: float):
        """Generador asíncrono de instantes simulados, uno por paso."""
        raise NotImplementedError("Fase 3 — RF-05: reloj de co-simulación")
        yield 0.0  # pragma: no cover  (hace de esta función un generador asíncrono)
