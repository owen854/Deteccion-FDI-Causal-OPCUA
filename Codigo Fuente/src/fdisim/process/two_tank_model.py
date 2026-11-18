"""Modelo dinámico de dos tanques en cascada (RF-01, RF-02).

Ecuaciones de balance de masa con descarga por gravedad (ley de Torricelli)::

    A1 · dh1/dt = q_in − s1·a1·√(2 g h1) − fuga1 + q_extra1
    A2 · dh2/dt = s1·a1·√(2 g h1) − s2·a2·√(2 g h2) − fuga2 + q_extra2

donde ``s_i`` (escala del área de descarga), ``fuga_i`` y ``q_extra_i`` (ruido de proceso) son
perturbaciones legítimas (RF-04). Sin perturbaciones se reducen al modelo nominal.

Integración: ``scipy.integrate.solve_ivp`` (RK45 con control de error, por defecto) o
Runge-Kutta 4 de paso fijo (modo offline acelerado y determinista). Los niveles se saturan en
[0, H_max]; el exceso sobre H_max se considera desbordamiento.

Implementado en la Fase 2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scipy.integrate import solve_ivp

from fdisim.common.config import ConfigError

INTEGRATORS = ("solve_ivp", "rk4")
Levels = tuple[float, float]


def _require(condition: bool, field: str, message: str, value: Any) -> None:
    if not condition:
        raise ConfigError(f"{field}: {message} (valor: {value})")


@dataclass(frozen=True, slots=True)
class TankParams:
    area_cm2: float  # A, área transversal
    outlet_area_cm2: float  # a, área del orificio de salida
    max_height_cm: float  # H_max

    def __post_init__(self) -> None:
        self.validate("tank")

    def validate(self, prefix: str) -> None:
        _require(self.area_cm2 > 0, f"{prefix}.area_cm2", "debe ser positiva", self.area_cm2)
        _require(
            self.outlet_area_cm2 > 0,
            f"{prefix}.outlet_area_cm2",
            "debe ser positiva",
            self.outlet_area_cm2,
        )
        _require(
            self.outlet_area_cm2 < self.area_cm2,
            f"{prefix}.outlet_area_cm2",
            "debe ser menor que el área del tanque",
            self.outlet_area_cm2,
        )
        _require(
            self.max_height_cm > 0,
            f"{prefix}.max_height_cm",
            "debe ser positiva",
            self.max_height_cm,
        )

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], prefix: str) -> TankParams:
        try:
            return cls(
                float(cfg["area_cm2"]), float(cfg["outlet_area_cm2"]), float(cfg["max_height_cm"])
            )
        except KeyError as exc:
            raise ConfigError(f"{prefix}.{exc.args[0]}: campo obligatorio") from None
        except ConfigError as exc:
            raise ConfigError(str(exc).replace("tank.", f"{prefix}.", 1)) from None


@dataclass(frozen=True, slots=True)
class TwoTankParams:
    tank1: TankParams
    tank2: TankParams
    gravity_cm_s2: float = 981.0

    def __post_init__(self) -> None:
        _require(
            self.gravity_cm_s2 > 0, "plant.gravity_cm_s2", "debe ser positiva", self.gravity_cm_s2
        )

    @classmethod
    def from_config(cls, plant: Mapping[str, Any]) -> TwoTankParams:
        return cls(
            TankParams.from_config(plant.get("tank1", {}), "plant.tank1"),
            TankParams.from_config(plant.get("tank2", {}), "plant.tank2"),
            float(plant.get("gravity_cm_s2", 981.0)),
        )


class TwoTankModel:
    """Dinámica no lineal del proceso. Estado ``(h1, h2)`` en cm; entrada ``q_in`` en cm³/s."""

    def __init__(self, params: TwoTankParams, integrator: str = "solve_ivp") -> None:
        if integrator not in INTEGRATORS:
            raise ConfigError(f"simulation.integrator: use {INTEGRATORS} (valor: {integrator})")
        self.params = params
        self.integrator = integrator
        self._k1 = params.tank1.outlet_area_cm2 * math.sqrt(2.0 * params.gravity_cm_s2)
        self._k2 = params.tank2.outlet_area_cm2 * math.sqrt(2.0 * params.gravity_cm_s2)

    def outflows(self, h: Levels, effects: Mapping[str, float] | None = None) -> Levels:
        """Caudales de descarga ``(q1, q2)`` [cm³/s]."""
        e = effects or {}
        q1 = e.get("tank1.outlet_scale", 1.0) * self._k1 * math.sqrt(max(h[0], 0.0))
        q2 = e.get("tank2.outlet_scale", 1.0) * self._k2 * math.sqrt(max(h[1], 0.0))
        return q1, q2

    def derivatives(
        self, h: Levels, q_in: float, effects: Mapping[str, float] | None = None
    ) -> Levels:
        """Devuelve ``(dh1/dt, dh2/dt)`` [cm/s]."""
        e = effects or {}
        q1, q2 = self.outflows(h, e)
        leak1 = e.get("tank1.leak", 0.0) if h[0] > 0 else 0.0
        leak2 = e.get("tank2.leak", 0.0) if h[1] > 0 else 0.0
        dh1 = (q_in - q1 - leak1 + e.get("tank1.extra_inflow", 0.0)) / self.params.tank1.area_cm2
        dh2 = (q1 - q2 - leak2 + e.get("tank2.extra_inflow", 0.0)) / self.params.tank2.area_cm2
        return dh1, dh2

    def step(
        self, h: Levels, q_in: float, dt: float, effects: Mapping[str, float] | None = None
    ) -> Levels:
        """Integra un paso ``dt`` con entrada constante y devuelve el estado saturado."""
        if self.integrator == "rk4":
            h1, h2 = self._rk4(h, q_in, dt, effects)
        else:
            sol = solve_ivp(
                lambda _t, y: self.derivatives((y[0], y[1]), q_in, effects),
                (0.0, dt),
                [h[0], h[1]],
                method="RK45",
                rtol=1e-7,
                atol=1e-9,
            )
            h1, h2 = float(sol.y[0, -1]), float(sol.y[1, -1])
        return (
            min(max(h1, 0.0), self.params.tank1.max_height_cm),
            min(max(h2, 0.0), self.params.tank2.max_height_cm),
        )

    def _rk4(
        self, h: Levels, q_in: float, dt: float, effects: Mapping[str, float] | None
    ) -> Levels:
        f = self.derivatives
        k1 = f(h, q_in, effects)
        k2 = f((h[0] + dt / 2 * k1[0], h[1] + dt / 2 * k1[1]), q_in, effects)
        k3 = f((h[0] + dt / 2 * k2[0], h[1] + dt / 2 * k2[1]), q_in, effects)
        k4 = f((h[0] + dt * k3[0], h[1] + dt * k3[1]), q_in, effects)
        return (
            h[0] + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]),
            h[1] + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]),
        )

    def steady_state(self, q_in: float) -> Levels:
        """Estado estacionario analítico sin perturbaciones: ``h_i = (q_in / a_i)² / (2 g)``."""
        if q_in < 0:
            raise ValueError("q_in debe ser no negativo")
        g2 = 2.0 * self.params.gravity_cm_s2
        return (
            (q_in / self.params.tank1.outlet_area_cm2) ** 2 / g2,
            (q_in / self.params.tank2.outlet_area_cm2) ** 2 / g2,
        )

    def equilibrium_inflow(self, h2: float) -> float:
        """Caudal de entrada que mantiene ``h2`` en equilibrio: ``q = a2·√(2 g h2)``."""
        return self._k2 * math.sqrt(max(h2, 0.0))
