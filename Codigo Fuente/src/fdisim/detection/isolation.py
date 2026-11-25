"""Identificación de la variable comprometida por residuos estructurados (RF-37).

Cada residuo depende solo de la ecuación de su variable y de los padres observados
(``detection.residuals``), así que un ataque deja una firma sobre el grafo:

- LT-101 → residuos de LT-101 y de su hijo LT-102 (el gemelo de h2 usa h1 como entrada).
- LT-102 → solo el residuo de LT-102. La ley de control sigue siendo consistente porque el
  controlador y el monitor reciben el mismo valor falso.
- FT-101 → residuos de FT-101 (q_in = k_p·ū) y de LT-101 (h1 usa q_in como entrada).
- P-101 (orden alterada hacia la planta y eco oculto) → solo el residuo de FT-101: el caudal
  real ya no corresponde a la orden que ven los clientes, pero los niveles siguen siendo
  coherentes con el caudal medido.

La identificación elige la variable cuya firma mejor explica las variables con residuos en
alarma, ponderadas por su severidad (índice de Jaccard ponderado: cada variable en alarma pesa
su puntuación y cada miembro de la firma que no está en alarma pesa 1, el nivel de un límite).
Así, un residuo muy fuera de su límite pesa más que uno que apenas lo roza. Los empates se
resuelven a favor de la variable cuyo propio residuo está en alarma.

Limitación conocida: un sesgo sobre FT-101 que no alcance a alterar el residuo de LT-101 se
confunde con un ataque a P-101 (ambas firmas contienen FT-101).

Implementado en la Fase 6.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from fdisim.common.types import FT_101, LT_101, LT_102, P_101

SIGNATURES: Mapping[str, frozenset[str]] = {
    LT_101: frozenset({LT_101, LT_102}),
    LT_102: frozenset({LT_102}),
    FT_101: frozenset({FT_101, LT_101}),
    P_101: frozenset({FT_101}),
}


def isolate(alarmed_residuals: Iterable[str], scores: Mapping[str, float]) -> str | None:
    """Devuelve la etiqueta más probablemente comprometida o ``None`` si no hay alarma.

    ``alarmed_residuals`` son las variables con algún residuo en alarma y ``scores`` su
    puntuación (p. ej., el mayor ``|z|`` normalizado por su límite).
    """
    alarmed = frozenset(alarmed_residuals)
    if not alarmed:
        return None
    weight = {tag: max(float(scores.get(tag, 1.0)), 1e-9) for tag in alarmed}
    total = sum(weight.values())

    def rank(tag: str) -> tuple[float, bool, float]:
        signature = SIGNATURES[tag]
        explained = sum(weight[t] for t in alarmed & signature)
        missing = len(signature - alarmed)
        return explained / (total + missing), tag in alarmed, weight.get(tag, 0.0)

    return max(SIGNATURES, key=rank)
