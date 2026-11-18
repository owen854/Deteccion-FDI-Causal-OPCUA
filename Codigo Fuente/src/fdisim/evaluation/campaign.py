"""Campañas experimentales automatizadas (RF-43).

Expande ``config/campaigns/*.yaml`` en condiciones (escenario × barrido × repetición),
ejecuta cada condición (offline o en red), procesa con ambos detectores y consolida las
métricas en una tabla por condición y repetición.

Fase de implementación: Fase 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Condition:
    scenario: str
    overrides: dict[str, Any]
    repetition: int
    seed: int


def expand_campaign(campaign_path: Path) -> list[Condition]:
    raise NotImplementedError("Fase 8 — RF-43: expansión de la campaña")


def run_campaign(campaign_path: Path, out_dir: Path | None = None) -> Path:
    """Ejecuta la campaña completa y devuelve la carpeta de resultados."""
    raise NotImplementedError("Fase 8 — RF-43: ejecución de campañas")
