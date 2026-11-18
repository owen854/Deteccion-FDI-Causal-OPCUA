"""Visualización del grafo causal con resaltado de inconsistencias (RF-50).

Se dibuja con ECharts (serie ``graph``). Fase de implementación: Fase 7.
"""

from __future__ import annotations

from fdisim.causal.prior_graph import CausalLink


def causal_graph_view(links: tuple[CausalLink, ...], highlighted: set[str] | None = None) -> None:
    raise NotImplementedError("Fase 7 — RF-50: grafo causal")
