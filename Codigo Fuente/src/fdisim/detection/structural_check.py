"""Verificación de consistencia estructural por ventanas (RF-35).

En ventanas deslizantes estima la fuerza de los enlaces esperados del grafo de referencia
(p. ej. P-101 → FT-101 → LT-101 → LT-102) y la compara con su distribución en operación
normal. Un replay rompe la dependencia entre la actuación actual y el nivel reproducido; un
enlace que desaparece (o uno espurio que aparece) genera una alarma ``STRUCTURAL``.

Diferido en la versión v1 (prioridad «Debería» en el ERS): el residuo del gemelo causal en
horizonte cubre el replay con excitación (cambio de consigna o perturbación durante el ataque).
Queda para una versión posterior, junto con la marca de agua física (RF-39).
"""

from __future__ import annotations

from collections.abc import Mapping

from fdisim.causal.prior_graph import CausalLink


class StructuralConsistencyChecker:
    def __init__(self, links: tuple[CausalLink, ...], window: int, step: int) -> None:
        self.links = links
        self.window = window
        self.step = step

    def fit(self, normal_data: object) -> StructuralConsistencyChecker:
        raise NotImplementedError(
            "Diferido (v2) — RF-35: distribución normal de la fuerza de enlaces"
        )

    def update(self, values: Mapping[str, float]) -> dict[str, float]:
        """Devuelve ``{"src->dst@lag": puntuación}`` cuando se completa un paso de ventana."""
        raise NotImplementedError("Diferido (v2) — RF-35: verificación estructural")
