"""Ejecución de un escenario en modo offline: sin red, determinista y acelerado (RF-27, RF-38).

Encadena en un solo bucle las mismas clases del modo en red: ``Plant`` → ``FdiInjector`` →
alineación → ``PIDController`` (lee el valor posiblemente falsificado, como en la red) →
detectores. Permite campañas de cientos de corridas (RNF-04: ≥ 100× tiempo real) y
reproducibilidad exacta por semilla (RNF-08). No mide latencias de red.

Fase de implementación: Fase 4.
"""

from __future__ import annotations

from pathlib import Path


def run_scenario_offline(
    scenario_path: Path,
    config_path: Path | None = None,
    seed: int | None = None,
    overrides: dict | None = None,
) -> Path:
    """Ejecuta el escenario y devuelve la carpeta de la corrida (``data/raw/<run_id>``)."""
    raise NotImplementedError("Fase 4 — RF-27/RF-38: ejecución offline")
