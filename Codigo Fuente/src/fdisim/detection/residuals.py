"""Cálculo de residuos causales (RF-33).

- Residuo a un paso: ``r_i(t) = x_i^obs(t) − f_i(padres observados)``.
- Residuo multi-paso: diferencia entre la observación y la simulación del gemelo causal en
  horizonte H (``StructuralCausalModel.simulate``), más sensible a sesgos y rampas lentas.

Ambos se normalizan con las estadísticas de operación normal: ``z = (r − μ) / σ``.

Fase de implementación: Fase 6.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdisim.causal.scm import StructuralCausalModel


class ResidualComputer:
    def __init__(self, scm: StructuralCausalModel, horizon: int, history_len: int) -> None:
        self.scm = scm
        self.horizon = horizon
        self.history_len = history_len

    def update(self, values: Mapping[str, float]) -> dict[str, float]:
        """Añade la muestra al historial y devuelve ``{"<tag>:1": z, "<tag>:H": z}``."""
        raise NotImplementedError("Fase 6 — RF-33: residuos a un paso y multi-paso")
