"""Reportes de campaña (RF-44, RF-46).

Genera ``results/<campaña>/``: ``metrics.csv`` (por condición y repetición), ``summary.csv``,
``report.html`` y ``figures/*.png|svg`` a ≥ 300 dpi (matplotlib) para el informe y el artículo.
Todas las tablas y figuras se regeneran desde los datos crudos.

Fase de implementación: Fase 8.
"""

from __future__ import annotations

from pathlib import Path


def build_report(campaign_dir: Path) -> Path:
    """Genera el reporte y devuelve la ruta de ``report.html``."""
    raise NotImplementedError("Fase 8 — RF-46: reporte de campaña")
