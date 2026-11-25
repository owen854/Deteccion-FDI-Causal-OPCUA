"""Reglas de decisión sobre residuos normalizados (RF-34).

- ``ThresholdRule``: alarma si ``z > τ⁺`` o ``z < τ⁻``. Por defecto es simétrica
  (``τ⁻ = −τ⁺``); la calibración usa límites asimétricos porque algunos residuos no son
  simétricos en operación normal (p. ej., la perturbación legítima del área de salida del
  tanque 2 solo desplaza el residuo de LT-102 hacia abajo).
- ``Cusum``: CUSUM bilateral (Page, 1954) ``S⁺ = max(0, S⁺ + z − k)``,
  ``S⁻ = max(0, S⁻ − z − k)``; alarma si ``S⁺ > h`` o ``S⁻ > h``.
- ``Ewma``: ``E = λ·z + (1 − λ)·E``; alarma si ``|E| > L·√(λ / (2 − λ))``.
- ``AlarmLatch``: mantiene la alarma activa ``hold_s`` segundos para evitar intermitencias.

Cada ``update`` devuelve ``True`` si la regla está en alarma tras procesar la muestra. Las
funciones ``*_statistic`` calculan la misma recursión sobre una serie completa; la calibración
las usa para fijar los límites en validación (``calibrate_threshold``, ``calibrate_limits``).

Implementado en la Fase 6.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np


class ThresholdRule:
    def __init__(self, threshold: float, lower: float | None = None) -> None:
        self.threshold = threshold
        self.lower = -threshold if lower is None else lower

    def update(self, z: float) -> bool:
        return math.isfinite(z) and (z > self.threshold or z < self.lower)


class Cusum:
    def __init__(self, k: float, h: float, cap: float | None = None) -> None:
        self.k = k
        self.h = h
        self.cap = cap if cap is not None and math.isfinite(cap) else None  # saturación
        self.reset()

    def reset(self) -> None:
        self.s_pos = 0.0
        self.s_neg = 0.0

    @property
    def statistic(self) -> float:
        return max(self.s_pos, self.s_neg)

    def update(self, z: float) -> bool:
        if math.isfinite(z):
            self.s_pos = max(0.0, self.s_pos + z - self.k)
            self.s_neg = max(0.0, self.s_neg - z - self.k)
            if self.cap is not None:
                self.s_pos = min(self.s_pos, self.cap)
                self.s_neg = min(self.s_neg, self.cap)
        return self.statistic > self.h


class Ewma:
    def __init__(self, lam: float, L: float) -> None:  # noqa: N803  (notación estándar)
        self.lam = lam
        self.L = L
        self.reset()

    def reset(self) -> None:
        self.value = 0.0

    @property
    def limit(self) -> float:
        return self.L * math.sqrt(self.lam / (2.0 - self.lam))

    def update(self, z: float) -> bool:
        if math.isfinite(z):
            self.value = self.lam * z + (1.0 - self.lam) * self.value
        return abs(self.value) > self.limit


class AlarmLatch:
    def __init__(self, hold_s: float) -> None:
        self.hold_s = hold_s
        self.reset()

    def reset(self) -> None:
        self._last_true: float | None = None

    def update(self, t: float, raw_alarm: bool) -> bool:
        if raw_alarm:
            self._last_true = t
            return True
        return self._last_true is not None and t - self._last_true < self.hold_s - 1e-9


def calibrate_threshold(normal_scores: Sequence[float], target_fpr: float) -> float:
    """Cuantil ``1 − target_fpr`` de ``|z|`` en datos normales de validación."""
    z = np.abs(np.asarray(normal_scores, dtype=float))
    z = z[np.isfinite(z)]
    if z.size == 0:
        raise ValueError("Sin puntuaciones normales para calibrar")
    return float(np.quantile(z, 1.0 - target_fpr))


# ---------------------------------------------------------------------- series completas
def cusum_statistic(z: np.ndarray, k: float) -> np.ndarray:
    """``max(S⁺, S⁻)`` muestra a muestra (misma recursión que ``Cusum``)."""
    out = np.empty(len(z))
    s_pos = s_neg = 0.0
    for i, value in enumerate(z):
        if math.isfinite(value):
            s_pos = max(0.0, s_pos + value - k)
            s_neg = max(0.0, s_neg - value - k)
        out[i] = max(s_pos, s_neg)
    return out


def ewma_statistic(z: np.ndarray, lam: float) -> np.ndarray:
    """``|E|`` muestra a muestra (misma recursión que ``Ewma``)."""
    out = np.empty(len(z))
    e = 0.0
    for i, value in enumerate(z):
        if math.isfinite(value):
            e = lam * value + (1.0 - lam) * e
        out[i] = abs(e)
    return out


def latch_series(raw: np.ndarray, hold_samples: int) -> np.ndarray:
    """Retención aplicada a una serie booleana (equivale a ``AlarmLatch`` en la rejilla)."""
    raw = np.asarray(raw, dtype=bool)
    if hold_samples <= 1 or not raw.any():
        return raw.copy()
    kernel = np.ones(hold_samples, dtype=int)
    return np.convolve(raw.astype(int), kernel)[: len(raw)] > 0


def calibrate_limits(
    alarm_rate: Callable[[float], float], target_fpr: float, *, iterations: int = 30
) -> tuple[float, float]:
    """Mayor nivel por regla ``ε`` cuyo FPR combinado (con retención) no supera el objetivo.

    ``alarm_rate(ε)`` devuelve el FPR medido en validación cuando cada regla se calibra en su
    cuantil ``1 − ε``. Es monótona en ε, así que basta una bisección (en escala logarítmica).
    Devuelve ``(ε, FPR medido)``.
    """
    lo, hi = math.log(1e-7), math.log(max(target_fpr, 1e-6))
    best = (math.exp(lo), alarm_rate(math.exp(lo)))
    if alarm_rate(math.exp(hi)) <= target_fpr:
        return math.exp(hi), alarm_rate(math.exp(hi))
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        rate = alarm_rate(math.exp(mid))
        if rate <= target_fpr:
            lo, best = mid, (math.exp(mid), rate)
        else:
            hi = mid
    return best
