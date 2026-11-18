"""Perfil de consigna por escenario (RF-09).

Lista de escalones ``(t_s, valor)``; la consigna vigente es la del último escalón con
``t_s <= t`` (antes del primero rige el primer valor). La HMI puede fijar una consigna
manual con ``override`` y liberarla con ``override(None)``.

Implementado en la Fase 2.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping
from typing import Any

from fdisim.common.config import ConfigError


class SetpointProfile:
    def __init__(self, points: Iterable[tuple[float, float]]) -> None:
        pts = sorted((float(t), float(v)) for t, v in points)
        if not pts:
            raise ValueError("El perfil de consigna necesita al menos un punto")
        self.points = pts
        self._times = [t for t, _ in pts]
        self._override: float | None = None

    @classmethod
    def from_config(cls, items: Iterable[Mapping[str, Any]]) -> SetpointProfile:
        try:
            return cls((item["t_s"], item["value_cm"]) for item in items)
        except KeyError as exc:
            raise ConfigError(f"setpoint_profile.{exc.args[0]}: campo obligatorio") from None

    def value_at(self, t: float) -> float:
        if self._override is not None:
            return self._override
        i = bisect.bisect_right(self._times, t) - 1
        return self.points[max(i, 0)][1]

    def change_times(self) -> list[float]:
        """Instantes de los cambios de consigna (excluye el valor inicial)."""
        return self._times[1:]

    def override(self, value: float | None) -> None:
        """Fija (o libera con ``None``) una consigna manual desde la HMI."""
        self._override = None if value is None else float(value)
