"""Reglas de decisión sobre residuos normalizados (RF-34).

- ``ThresholdRule``: alarma si ``|z| > τ``, con τ calibrado en validación para el FPR objetivo.
- ``Cusum``: CUSUM bilateral (Page, 1954) ``S⁺ = max(0, S⁺ + z − k)``,
  ``S⁻ = max(0, S⁻ − z − k)``; alarma si ``S⁺ > h`` o ``S⁻ > h``.
- ``Ewma``: ``E = λ·z + (1 − λ)·E``; alarma si ``|E| > L·√(λ / (2 − λ))``.
- ``AlarmLatch``: mantiene la alarma activa ``hold_s`` segundos para evitar intermitencias.

Cada ``update`` devuelve ``True`` si la regla está en alarma tras procesar la muestra.
Fase de implementación: Fase 6.
"""

from __future__ import annotations


class ThresholdRule:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def update(self, z: float) -> bool:
        raise NotImplementedError("Fase 6 — RF-34: umbral calibrado")


class Cusum:
    def __init__(self, k: float, h: float) -> None:
        self.k = k
        self.h = h

    def reset(self) -> None:
        raise NotImplementedError("Fase 6 — RF-34: CUSUM")

    def update(self, z: float) -> bool:
        raise NotImplementedError("Fase 6 — RF-34: CUSUM")


class Ewma:
    def __init__(self, lam: float, L: float) -> None:  # noqa: N803  (notación estándar)
        self.lam = lam
        self.L = L

    def reset(self) -> None:
        raise NotImplementedError("Fase 6 — RF-34: EWMA")

    def update(self, z: float) -> bool:
        raise NotImplementedError("Fase 6 — RF-34: EWMA")


class AlarmLatch:
    def __init__(self, hold_s: float) -> None:
        self.hold_s = hold_s

    def update(self, t: float, raw_alarm: bool) -> bool:
        raise NotImplementedError("Fase 6 — RF-34: retención de alarmas")


def calibrate_threshold(normal_scores: list[float], target_fpr: float) -> float:
    """Cuantil ``1 − target_fpr`` de ``|z|`` en datos normales de validación."""
    raise NotImplementedError("Fase 6 — RF-34: calibración del umbral")
