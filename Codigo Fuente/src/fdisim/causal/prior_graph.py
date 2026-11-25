"""Grafo causal a priori derivado de la física del proceso (RF-28; ERS Figura 2).

Enlaces ``fuente(t − lag) → destino(t)``. Los enlaces con ``lag = 0`` son contemporáneos
(ley de control y actuador); los de ``lag = 1`` provienen de los balances de masa y de la
memoria integral del PID.

El grafo es temporal: entre dos variables puede haber varios enlaces con distinto retardo,
por eso se representa como ``networkx.MultiDiGraph`` (una arista por retardo, con clave
``lag<k>``). Se exporta a GraphML o JSON (RNF-13).

Implementado en la Fase 5.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102

NODES: tuple[str, ...] = (SP_102, P_101, FT_101, LT_101, LT_102)
EXOGENOUS: frozenset[str] = frozenset({SP_102})  # la fija el operador o el escenario


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


def edge_set(links: Iterable[Any]) -> set[tuple[str, str, int]]:
    """Conjunto de aristas ``(fuente, destino, retardo)`` de cualquier lista de enlaces."""
    return {(link.source, link.target, int(link.lag)) for link in links}


def build_prior_graph(links: Iterable[CausalLink] = PHYSICAL_LINKS) -> Any:
    """Devuelve un ``networkx.MultiDiGraph`` con atributos ``lag`` y ``mechanism`` por arista."""
    import networkx as nx

    graph = nx.MultiDiGraph(name="grafo causal")
    graph.add_nodes_from(NODES)
    for link in links:
        graph.add_node(link.source)
        graph.add_node(link.target)
        graph.add_edge(
            link.source,
            link.target,
            key=f"lag{link.lag}",
            lag=int(link.lag),
            mechanism=link.mechanism,
        )
    return graph


def links_from_graph(graph: Any) -> tuple[CausalLink, ...]:
    """Inverso de ``build_prior_graph``."""
    links = [
        CausalLink(str(u), str(v), int(data["lag"]), str(data.get("mechanism", "")))
        for u, v, data in graph.edges(data=True)
    ]
    return tuple(sorted(links, key=lambda link: (link.target, link.lag, link.source)))


def export_graph(graph: Any, path: str | Path, fmt: str = "graphml") -> Path:
    """Exporta a GraphML o JSON (RNF-13)."""
    import networkx as nx

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "graphml":
        nx.write_graphml(graph, path)
    elif fmt == "json":
        data = {
            "nodes": list(graph.nodes),
            "links": [
                {"source": u, "target": v, "lag": d["lag"], "mechanism": d.get("mechanism", "")}
                for u, v, d in graph.edges(data=True)
            ],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        raise ValueError(f"Formato no soportado: {fmt}")
    return path


def load_graph(path: str | Path) -> Any:
    """Lee un grafo exportado en GraphML o JSON."""
    import networkx as nx

    path = Path(path)
    if path.suffix == ".graphml":
        graph = nx.read_graphml(path, force_multigraph=True)
        for _, _, data in graph.edges(data=True):
            data["lag"] = int(data["lag"])
        return graph
    data = json.loads(path.read_text(encoding="utf-8"))
    return build_prior_graph(
        CausalLink(item["source"], item["target"], int(item["lag"]), item.get("mechanism", ""))
        for item in data["links"]
    )
