"""Comparación y consolidación de grafos causales (RF-30).

Métricas entre un grafo de referencia y uno estimado:

- **SHD** (distancia estructural de Hamming): número de aristas que hay que agregar o quitar
  para pasar de uno a otro. Un enlace contemporáneo invertido cuenta como una sola diferencia.
- **Precisión y exhaustividad de enlaces**, con retardo (``(fuente, destino, retardo)``) y sin
  retardo (pares ``(fuente, destino)``). La versión sin retardo permite comparar grafos
  estimados con distinta resolución temporal.

Los enlaces hacia variables exógenas (la consigna) no forman parte del modelo de la planta y se
excluyen de la comparación.

La consolidación parte del grafo físico y aplica decisiones explícitas (agregar o quitar un
enlace, cada una con su justificación). Además, clasifica cada discrepancia entre el grafo
físico y los grafos aprendidos con su causa probable, para el estudio comparativo.

Implementado en la Fase 5.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fdisim.causal.discovery import DiscoveredLink
from fdisim.causal.prior_graph import EXOGENOUS, CausalLink, edge_set
from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102

Edge = tuple[str, str, int]  # (fuente, destino, retardo)


def _clean(edges: Iterable[Edge]) -> set[Edge]:
    return {(s, t, int(lag)) for s, t, lag in edges if t not in EXOGENOUS}


def structural_hamming_distance(reference: Iterable[Edge], estimated: Iterable[Edge]) -> int:
    ref, est = _clean(reference), _clean(estimated)
    missing, extra = ref - est, est - ref
    reversed_pairs = {(s, t) for s, t, lag in missing if lag == 0 and (t, s, 0) in extra}
    return len(missing) + len(extra) - len(reversed_pairs)


def edge_precision_recall(
    reference: Iterable[Edge], estimated: Iterable[Edge], use_lag: bool = True
) -> tuple[float, float]:
    ref, est = _clean(reference), _clean(estimated)
    if not use_lag:
        ref = {(s, t, 0) for s, t, _ in ref}
        est = {(s, t, 0) for s, t, _ in est}
    hits = len(ref & est)
    precision = hits / len(est) if est else 1.0
    recall = hits / len(ref) if ref else 1.0
    return precision, recall


def compare(reference: Iterable[Edge], estimated: Iterable[Edge]) -> dict[str, float]:
    """Todas las métricas de un grafo estimado frente a uno de referencia."""
    reference, estimated = list(reference), list(estimated)
    p, r = edge_precision_recall(reference, estimated)
    p0, r0 = edge_precision_recall(reference, estimated, use_lag=False)
    return {
        "edges": len(_clean(estimated)),
        "shd": structural_hamming_distance(reference, estimated),
        "precision": p,
        "recall": r,
        "precision_sin_retardo": p0,
        "recall_sin_retardo": r0,
    }


def discovered_edges(links: Iterable[DiscoveredLink]) -> set[Edge]:
    """Aristas de un descubrimiento (las contemporáneas sin orientar, en ambos sentidos)."""
    out: set[Edge] = set()
    for link in links:
        out.add((link.source, link.target, link.lag))
        if link.orientation != "-->":
            out.add((link.target, link.source, link.lag))
    return out


# ---------------------------------------------------------------------- consolidación
@dataclass(frozen=True, slots=True)
class Decision:
    action: str  # "add" | "remove"
    reason: str


@dataclass(slots=True)
class ConsolidationResult:
    links: tuple[CausalLink, ...]
    table: list[dict[str, Any]] = field(default_factory=list)


def classify_discrepancy(source: str, target: str, lag: int) -> str:
    """Causa probable de un enlace aprendido que no tiene mecanismo físico directo."""
    if source == target == FT_101:
        return (
            "memoria de la bomba (primer orden) vista a través de una medición ruidosa; el modelo "
            "la representa con la historia de la orden P-101"
        )
    if source == target:
        return (
            "auto-enlace de orden superior: el estado del tanque es latente y solo se observa "
            "con ruido, así que condicionar en mediciones pasadas no bloquea la dependencia"
        )
    if source == SP_102 and target != P_101:
        return "efecto indirecto de la consigna a través del controlador (lazo cerrado)"
    if source == P_101 and target in (LT_101, LT_102):
        return (
            "efecto indirecto a través del caudal: FT-101 ≈ k_p·P-101 es casi determinista y "
            "P-101 no tiene ruido de medición, por eso las pruebas lo prefieren como causa"
        )
    if source in (LT_101, LT_102) and target in (FT_101, P_101):
        return "realimentación a través del controlador (lazo cerrado)"
    if source == FT_101 and target in (LT_102, P_101):
        return "efecto indirecto a través del tanque 1 o colinealidad del lazo cerrado"
    if source == LT_102 and target == LT_101:
        return "sin mecanismo físico (el tanque 2 no influye en el tanque 1): correlación del lazo"
    return "sin mecanismo físico identificado"


def consolidate(
    prior: tuple[CausalLink, ...],
    discovered: Mapping[str, list[DiscoveredLink]],
    justification: Mapping[Edge, Decision],
) -> ConsolidationResult:
    """Grafo de referencia final a partir del físico, de los aprendidos y de las decisiones.

    ``discovered`` asocia un nombre de método (p. ej. «PCMCI+ 0,5 s») con sus enlaces; la tabla
    resultante indica, por par de variables, en qué retardos lo encontró cada método, si es
    físico, si queda en la referencia y por qué.
    """
    links = {(link.source, link.target, link.lag): link for link in prior}
    for edge, decision in justification.items():
        if decision.action == "remove":
            links.pop(edge, None)
        elif decision.action == "add":
            links[edge] = CausalLink(edge[0], edge[1], edge[2], decision.reason)
        else:
            raise ValueError(f"Acción desconocida: {decision.action}")
    reference = tuple(sorted(links.values(), key=lambda lk: (lk.target, lk.lag, lk.source)))

    found: dict[tuple[str, str], dict[str, list[int]]] = {}
    for method, method_links in discovered.items():
        for s, t, lag in sorted(discovered_edges(method_links)):
            if t in EXOGENOUS:
                continue
            found.setdefault((s, t), {}).setdefault(method, []).append(lag)
    physical = edge_set(prior)
    ref_edges = edge_set(reference)
    pairs = {(s, t) for s, t, _ in physical | ref_edges} | set(found)
    table = []
    for s, t in sorted(pairs, key=lambda p: (p[1], p[0])):
        phys_lags = sorted(lag for a, b, lag in physical if (a, b) == (s, t))
        ref_lags = sorted(lag for a, b, lag in ref_edges if (a, b) == (s, t))
        if ref_lags or phys_lags:
            mechanisms = {(lk.source, lk.target, lk.lag): lk.mechanism for lk in reference}
            reasons: list[str] = []
            for lag in ref_lags:
                edge = (s, t, lag)
                text = justification[edge].reason if edge in justification else mechanisms[edge]
                reasons.append(f"τ={lag}: {text}")
            for lag in phys_lags:
                if lag not in ref_lags:
                    edge = (s, t, lag)
                    text = justification[edge].reason if edge in justification else "eliminado"
                    reasons.append(f"τ={lag} se elimina: {text}")
            reason = " · ".join(dict.fromkeys(reasons))
            if ref_lags and not found.get((s, t)):
                reason += " (se mantiene por la física; ningún método lo recupera)"
        else:
            reason = classify_discrepancy(s, t, 0)
        table.append(
            {
                "source": s,
                "target": t,
                "physical_lags": phys_lags,
                "reference_lags": ref_lags,
                "found_by": found.get((s, t), {}),
                "reason": reason,
            }
        )
    return ConsolidationResult(reference, table)


# Decisiones de consolidación para la rejilla de detección de 0,5 s, justificadas con la física
# del proceso y con lo que encontraron PCMCI+ y Granger en el dataset v1 (estudio comparativo).
GRID_DECISIONS: dict[Edge, Decision] = {
    (P_101, FT_101, 0): Decision(
        "remove",
        "en la rejilla de 0,5 s la orden escrita en t se aplica durante (t, t+0,5 s] y la bomba "
        "es de primer orden (τ = 0,5 s): el efecto no es contemporáneo, aparece desde t+1",
    ),
    **{
        (P_101, FT_101, lag): Decision(
            "add",
            "dinámica de primer orden de la bomba (τ = 0,5 s): la orden de t−k sigue influyendo "
            "en el caudal; PCMCI+ y Granger lo encuentran en los retardos 1 a 3",
        )
        for lag in (1, 2, 3)
    },
    (LT_102, P_101, 1): Decision(
        "add",
        "forma incremental del PI: Δu(t) = Kp·[e(t) − e(t−1)] + Ki·Ts·e(t) depende del error "
        "anterior; Granger lo encuentra en el retardo 1",
    ),
    (SP_102, P_101, 1): Decision(
        "add",
        "forma incremental del PI: el error anterior e(t−1) incluye la consigna anterior; Granger "
        "lo encuentra en el retardo 1",
    ),
}
