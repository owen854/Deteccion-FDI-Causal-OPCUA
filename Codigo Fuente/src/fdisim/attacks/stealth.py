"""Restricciones de sigilo (RF-20).

``yₐ ← clip(yₐ, y_min, y_max)`` y ``|yₐ(k) − yₐ(k−1)| ≤ ρ_max·Δt``: el valor falso nunca sale
de la envolvente operativa ni cambia más rápido de lo plausible, por lo que un detector por
umbrales estáticos no lo detecta trivialmente.

Fase de implementación: Fase 4.
"""

from __future__ import annotations

from fdisim.common.types import StealthSpec


class StealthFilter:
    def __init__(self, spec: StealthSpec) -> None:
        self.spec = spec

    def apply(self, tag: str, fake_value: float, t: float) -> float:
        raise NotImplementedError("Fase 4 — RF-20: restricciones de sigilo")
