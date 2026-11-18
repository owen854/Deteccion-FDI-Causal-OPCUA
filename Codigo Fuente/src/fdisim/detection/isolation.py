"""Identificación de la variable comprometida por residuos estructurados (RF-37).

Firma esperada de residuos alterados según la variable atacada (ERS RF-37):

- LT-101 → residuos de LT-101 y de su hijo LT-102 (h2 usa h1 como entrada).
- LT-102 → solo el residuo de LT-102. La ley de control sigue siendo consistente porque el
  controlador y el monitor reciben el mismo valor falso.
- FT-101 → residuos de FT-101 (q_in = k_p·u) y de LT-101 (h1 usa q_in como entrada).

La identificación elige la variable cuya firma mejor explica el patrón observado de residuos
en alarma. La matriz se valida empíricamente en la Fase 6.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdisim.common.types import FT_101, LT_101, LT_102

SIGNATURES: Mapping[str, frozenset[str]] = {
    LT_101: frozenset({LT_101, LT_102}),
    LT_102: frozenset({LT_102}),
    FT_101: frozenset({FT_101, LT_101}),
}


def isolate(alarmed_residuals: set[str], scores: Mapping[str, float]) -> str | None:
    """Devuelve la etiqueta más probablemente comprometida o ``None`` si no hay alarma."""
    raise NotImplementedError("Fase 6 — RF-37: identificación por firma de residuos")
