"""Gráfica de tendencias en tiempo real (Plotly/ECharts) con bandas de ataque (RF-47, RF-49).

Fase de implementación: Fase 7.
"""

from __future__ import annotations

from fdisim.ui.state import UiState


def trend_chart(
    state: UiState, tags: list[str], title: str, show_attack_bands: bool = False
) -> None:
    raise NotImplementedError("Fase 7 — RF-47/RF-49: tendencias")
