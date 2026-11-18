"""Persistencia y versionado del modelo causal (RF-32).

Carpeta del modelo (``data/models/<nombre>``): ``graph.graphml``, ``scm.json`` (ecuaciones y
parámetros), ``residual_stats.json``, ``thresholds.json`` y ``manifest.json`` con el dataset de
origen y su hash.

Fase de implementación: Fase 5.
"""

from __future__ import annotations

from pathlib import Path

from fdisim.causal.scm import StructuralCausalModel


def save_model(
    model: StructuralCausalModel, graph: object, thresholds: dict[str, float], out_dir: Path
) -> Path:
    raise NotImplementedError("Fase 5 — RF-32: guardar modelo causal")


def load_model(model_dir: Path) -> tuple[StructuralCausalModel, object, dict[str, float]]:
    raise NotImplementedError("Fase 5 — RF-32: cargar modelo causal")
