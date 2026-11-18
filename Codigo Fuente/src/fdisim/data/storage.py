"""Persistencia de corridas con manifiesto de reproducibilidad (RF-26, RNF-08, RNF-13).

Estructura de una corrida::

    data/raw/<run_id>/
    ├── samples.parquet  ground_truth.parquet  attacks.parquet  alarms.parquet
    ├── config.yaml      (configuración efectiva completa)
    └── manifest.json    (RunManifest: semilla, commit, versiones, SHA-256 de cada archivo)

Fase de implementación: Fase 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fdisim.common.types import RunManifest


def sha256_file(path: Path) -> str:
    raise NotImplementedError("Fase 3 — RF-26: hash de archivos")


def write_run(
    run_dir: Path, tables: dict[str, Any], manifest: RunManifest, fmt: str = "parquet"
) -> Path:
    """Escribe las tablas (DataFrames) y el manifiesto; devuelve la ruta del manifiesto."""
    raise NotImplementedError("Fase 3 — RF-26: exportación de corridas")


def read_run(run_dir: Path) -> tuple[dict[str, Any], RunManifest]:
    """Lee una corrida y verifica los hashes del manifiesto."""
    raise NotImplementedError("Fase 3 — RF-26: lectura y verificación")
