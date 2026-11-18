"""Modelo dinámico de dos tanques en cascada (RF-01, RF-02).

Ecuaciones de balance de masa con descarga por gravedad (ley de Torricelli)::

    A1 · dh1/dt = q_in − a1 · sqrt(2 g h1)
    A2 · dh2/dt = a1 · sqrt(2 g h1) − a2 · sqrt(2 g h2)

Integración: ``scipy.integrate.solve_ivp`` (modo en red) o Runge-Kutta 4 de paso fijo
(modo offline acelerado y determinista). Los niveles se saturan en [0, H_max].

Fase de implementación: Fase 2. Dependencias previstas: NumPy, SciPy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TankParams:
    area_cm2: float  # A, área transversal
    outlet_area_cm2: float  # a, área del orificio de salida
    max_height_cm: float  # H_max


@dataclass(frozen=True, slots=True)
class TwoTankParams:
    tank1: TankParams
    tank2: TankParams
    gravity_cm_s2: float = 981.0


class TwoTankModel:
    """Dinámica no lineal del proceso. Estado: ``(h1, h2)`` en cm; entrada: ``q_in`` en cm³/s."""

    def __init__(self, params: TwoTankParams, integrator: str = "solve_ivp") -> None:
        self.params = params
        self.integrator = integrator

    def derivatives(self, h: tuple[float, float], q_in: float) -> tuple[float, float]:
        """Devuelve ``(dh1/dt, dh2/dt)`` para el estado ``h`` y el caudal de entrada ``q_in``."""
        raise NotImplementedError("Fase 2 — RF-01: ecuaciones de balance de masa")

    def step(self, h: tuple[float, float], q_in: float, dt: float) -> tuple[float, float]:
        """Integra un paso ``dt`` con entrada constante y devuelve el nuevo estado saturado."""
        raise NotImplementedError("Fase 2 — RF-01: integración numérica")

    def steady_state(self, q_in: float) -> tuple[float, float]:
        """Estado estacionario analítico: ``h_i = (q_in / a_i)² / (2 g)``."""
        raise NotImplementedError("Fase 2 — RF-01: estado estacionario analítico")
