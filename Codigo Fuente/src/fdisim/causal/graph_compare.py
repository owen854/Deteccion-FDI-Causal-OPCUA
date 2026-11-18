"""Comparación y consolidación de grafos causales (RF-30).

Métricas: distancia estructural de Hamming (SHD), precisión y exhaustividad de enlaces
(con y sin retardo). La consolidación parte del grafo físico y registra la justificación de
cada enlace añadido o descartado.

Fase de implementación: Fase 5.
"""

from __future__ import annotations

from collections.abc import Iterable

from fdisim.causal.discovery import DiscoveredLink
from fdisim.causal.prior_graph import CausalLink

Edge = tuple[str, str, int]  # (fuente, destino, retardo)


def structural_hamming_distance(reference: Iterable[Edge], estimated: Iterable[Edge]) -> int:
    raise NotImplementedError("Fase 5 — RF-30: SHD")


def edge_precision_recall(
    reference: Iterable[Edge], estimated: Iterable[Edge]
) -> tuple[float, float]:
    raise NotImplementedError("Fase 5 — RF-30: precisión y exhaustividad de enlaces")


def consolidate(
    prior: tuple[CausalLink, ...],
    discovered: dict[str, list[DiscoveredLink]],
    justification: dict[Edge, str],
) -> tuple[CausalLink, ...]:
    """Grafo de referencia final a partir del físico y de los aprendidos (por método)."""
    raise NotImplementedError("Fase 5 — RF-30: consolidación del grafo de referencia")
