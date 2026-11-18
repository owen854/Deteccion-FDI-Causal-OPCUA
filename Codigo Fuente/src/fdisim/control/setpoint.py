"""Perfil de consigna por escenario (RF-09).

Lista de escalones ``(t_s, valor)`` ordenados; la consigna vigente es la del último escalón
con ``t_s <= t``. La HMI puede sobrescribirla en ejecución (``override``).

Fase de implementación: Fase 2.
"""

from __future__ import annotations


class SetpointProfile:
    def __init__(self, points: list[tuple[float, float]]) -> None:
        if not points:
            raise ValueError("El perfil de consigna necesita al menos un punto")
        self.points = sorted(points)
        self._override: float | None = None

    def value_at(self, t: float) -> float:
        raise NotImplementedError("Fase 2 — RF-09: perfil de consigna")

    def override(self, value: float | None) -> None:
        """Fija (o libera con ``None``) una consigna manual desde la HMI."""
        self._override = value
