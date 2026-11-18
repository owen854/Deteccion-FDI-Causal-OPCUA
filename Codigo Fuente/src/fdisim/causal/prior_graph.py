"""Grafo causal a priori derivado de la física del proceso (RF-28; ERS Figura 2).

Enlaces ``fuente(t − lag) → destino(t)``. Los enlaces con ``lag = 0`` son contemporáneos
(ley de control y actuador); los de ``lag = 1`` provienen de los balances de masa y de la
memoria integral del PID.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102


@dataclass(frozen=True, slots=True)
class CausalLink:
    source: str
    target: str
    lag: int
    mechanism: str


PHYSICAL_LINKS: tuple[CausalLink, ...] = (
    CausalLink(LT_101, LT_101, 1, "inercia del tanque 1 (balance de masa)"),
    CausalLink(FT_101, LT_101, 1, "el caudal de entrada llena el tanque 1"),
    CausalLink(LT_101, LT_102, 1, "la descarga del tanque 1 alimenta el tanque 2"),
    CausalLink(LT_102, LT_102, 1, "inercia del tanque 2 (balance de masa)"),
    CausalLink(P_101, P_101, 1, "memoria de la acción integral del PID"),
    CausalLink(SP_102, P_101, 0, "la consigna entra en la ley de control"),
    CausalLink(LT_102, P_101, 0, "realimentación de la variable controlada"),
    CausalLink(P_101, FT_101, 0, "la bomba impone el caudal de entrada"),
)


def parents(tag: str, links: tuple[CausalLink, ...] = PHYSICAL_LINKS) -> tuple[CausalLink, ...]:
    """Enlaces cuyo destino es ``tag`` (padres causales con su retardo)."""
    return tuple(link for link in links if link.target == tag)


def build_prior_graph(links: tuple[CausalLink, ...] = PHYSICAL_LINKS) -> Any:
    """Devuelve un ``networkx.DiGraph`` con atributos ``lag`` y ``mechanism`` por arista."""
    raise NotImplementedError("Fase 5 — RF-28: grafo físico como networkx.DiGraph")


def export_graph(graph: Any, path: str, fmt: str = "graphml") -> None:
    """Exporta a GraphML o JSON (RNF-13)."""
    raise NotImplementedError("Fase 5 — RF-28: exportación del grafo")
