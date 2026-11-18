"""Ejecución de un escenario en modo en red: co-simulación con OPC UA real (RF-05, RF-22).

Crea la corrida (``run_id``, carpeta, manifiesto), lanza los componentes, espera la duración
del escenario, recoge la verdad de terreno y las etiquetas del plano de experimento y guarda
todo con ``data.storage``.

Fase de implementación: Fases 3 y 4.
"""

from __future__ import annotations

from pathlib import Path


def run_scenario_network(
    scenario_path: Path,
    config_path: Path | None = None,
    seed: int | None = None,
    with_ui: bool = False,
) -> Path:
    """Ejecuta el escenario y devuelve la carpeta de la corrida (``data/raw/<run_id>``)."""
    raise NotImplementedError("Fases 3–4 — RF-22/RF-54: ejecución en red")
