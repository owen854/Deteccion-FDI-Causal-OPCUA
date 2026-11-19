"""Reloj de co-simulación de paso fijo (RF-05).

Sincroniza el tiempo simulado con el reloj de pared mediante un factor de escala:
``t_pared = t_sim / time_scale``. Registra los pasos atrasados (overruns) para verificar
RNF-01 y la desviación acumulada (< 1 % en corridas de 10 min).

Cada paso ``k`` tiene un instante de pared programado ``inicio + k·Δt/escala``. El reloj espera
hasta ese instante absoluto (no un intervalo relativo), de modo que los retrasos de un paso no
se acumulan. ``epoch_of`` traduce un tiempo simulado a su instante programado en época Unix:
el servidor de planta lo usa como SourceTimestamp, lo que permite unir sin ambigüedad cada
muestra OPC UA con su registro de verdad de terreno.

En Windows, el temporizador del sistema tiene una resolución de ~15,6 ms; mientras el reloj
corre se solicita 1 ms (``timeBeginPeriod``) para que la espera sea precisa.

Implementado en la Fase 3.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ClockStats:
    steps: int = 0
    overruns: int = 0
    max_lag_s: float = 0.0
    total_lag_s: float = 0.0
    drift_pct: float = 0.0

    @property
    def mean_lag_s(self) -> float:
        return self.total_lag_s / self.steps if self.steps else 0.0

    def as_dict(self) -> dict[str, float]:
        out = asdict(self)
        out["mean_lag_s"] = self.mean_lag_s
        return out


@contextlib.contextmanager
def _high_resolution_timer() -> Iterator[None]:
    """Pide al sistema una resolución de temporizador de 1 ms mientras dura el bloque (Windows)."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
    try:
        yield
    finally:
        winmm.timeEndPeriod(1)


class CoSimClock:
    """Reloj asíncrono de paso fijo.

    Uso::

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
        self.start_epoch: float | None = None
        self._start_wall: float | None = None
        self._k = 0

    @property
    def sim_time(self) -> float:
        """Tiempo simulado actual [s]."""
        return self._k * self.dt_s

    @property
    def wall_period_s(self) -> float:
        """Duración de un paso en tiempo de pared [s]."""
        return self.dt_s / self.time_scale

    def epoch_of(self, sim_time: float) -> float:
        """Instante de pared programado (época Unix) que corresponde a ``sim_time``."""
        if self.start_epoch is None:
            raise RuntimeError("El reloj aún no ha arrancado")
        return self.start_epoch + sim_time / self.time_scale

    def sim_time_of(self, epoch: float) -> float:
        """Inversa de ``epoch_of``: tiempo simulado de un instante de pared."""
        if self.start_epoch is None:
            raise RuntimeError("El reloj aún no ha arrancado")
        return (epoch - self.start_epoch) * self.time_scale

    async def ticks(self, duration_s: float) -> AsyncIterator[float]:
        """Generador asíncrono de instantes simulados, uno por paso (Δt, 2Δt, …)."""
        steps = round(duration_s / self.dt_s)
        period = self.wall_period_s
        self.stats = ClockStats()
        self._k = 0
        with _high_resolution_timer():
            self._start_wall = time.perf_counter()
            self.start_epoch = time.time()
            for k in range(1, steps + 1):
                target = self._start_wall + k * period
                delay = target - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                lag = max(0.0, time.perf_counter() - target)
                if lag > period:
                    self.stats.overruns += 1
                self.stats.max_lag_s = max(self.stats.max_lag_s, lag)
                self.stats.total_lag_s += lag
                self._k = k
                self.stats.steps = k
                yield self.sim_time
            elapsed_wall = time.perf_counter() - self._start_wall
        if self.sim_time > 0:
            self.stats.drift_pct = (
                100.0 * abs(elapsed_wall * self.time_scale - self.sim_time) / self.sim_time
            )
