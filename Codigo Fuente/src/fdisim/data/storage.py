"""Persistencia de corridas con manifiesto de reproducibilidad (RF-26, RNF-08, RNF-13).

Estructura de una corrida::

    data/raw/<run_id>/
    ├── samples.parquet  ground_truth.parquet  (attacks, detections y alarms desde F4/F6)
    ├── config.yaml      (configuración efectiva completa)
    ├── summary.json     (indicadores de la corrida)
    └── manifest.json    (RunManifest: semilla, commit, versiones, SHA-256 de cada archivo)

``read_run`` recalcula los SHA-256 y rechaza la corrida si algún archivo fue alterado.

Implementado en la Fase 3.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from fdisim.common import paths
from fdisim.common.types import RunManifest, RunMode

MANIFEST = "manifest.json"
DATA_SUFFIXES = (".parquet", ".csv")
TRACKED_PACKAGES = (
    "fdisim",
    "asyncua",
    "cryptography",
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "tigramite",
    "statsmodels",
    "scikit-learn",
    "nicegui",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_run_id(scenario: str, now: datetime | None = None) -> str:
    """Identificador legible y ordenable: ``AAAAMMDD-HHMMSS_<escenario>``."""
    return f"{(now or datetime.now()):%Y%m%d-%H%M%S}_{scenario}"


def git_commit() -> str | None:
    """Commit actual del repositorio; añade ``-dirty`` si hay cambios sin confirmar."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=paths.PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=paths.PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{commit}-dirty" if dirty else commit


def package_versions(packages: tuple[str, ...] = TRACKED_PACKAGES) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in packages:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return out


def manifest_to_dict(manifest: RunManifest) -> dict[str, Any]:
    data = dataclasses.asdict(manifest)
    data["mode"] = manifest.mode.value
    return data


def manifest_from_dict(data: dict[str, Any]) -> RunManifest:
    return RunManifest(**{**data, "mode": RunMode(data["mode"])})


def finalize_run(run_dir: Path, manifest: RunManifest) -> Path:
    """Calcula el SHA-256 de todos los archivos de la corrida y escribe ``manifest.json``."""
    run_dir = Path(run_dir)
    files = {
        p.name: sha256_file(p)
        for p in sorted(run_dir.iterdir())
        if p.is_file() and p.name != MANIFEST
    }
    final = dataclasses.replace(manifest, files_sha256=files)
    path = run_dir / MANIFEST
    path.write_text(json.dumps(manifest_to_dict(final), indent=2, ensure_ascii=False), "utf-8")
    return path


def write_run(
    run_dir: Path, tables: dict[str, Any], manifest: RunManifest, fmt: str = "parquet"
) -> Path:
    """Escribe las tablas (DataFrames) y el manifiesto; devuelve la ruta del manifiesto."""
    if fmt not in ("parquet", "csv"):
        raise ValueError(f"Formato no soportado: {fmt}")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        target = run_dir / f"{name}.{fmt}"
        if fmt == "parquet":
            frame.to_parquet(target, index=False)
        else:
            frame.to_csv(target, index=False)
    return finalize_run(run_dir, manifest)


def verify_run(run_dir: Path) -> RunManifest:
    """Lee el manifiesto y comprueba los hashes; lanza ``ValueError`` si algo no coincide."""
    run_dir = Path(run_dir)
    path = run_dir / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"La corrida no tiene {MANIFEST}: {run_dir}")
    manifest = manifest_from_dict(json.loads(path.read_text(encoding="utf-8")))
    for name, expected in manifest.files_sha256.items():
        file = run_dir / name
        if not file.is_file():
            raise ValueError(f"Falta el archivo {name} declarado en el manifiesto")
        if sha256_file(file) != expected:
            raise ValueError(f"El archivo {name} no coincide con su SHA-256 (fue alterado)")
    return manifest


def read_run(run_dir: Path) -> tuple[dict[str, Any], RunManifest]:
    """Lee una corrida y verifica los hashes del manifiesto."""
    import pandas as pd

    manifest = verify_run(run_dir)
    tables: dict[str, Any] = {}
    for name in manifest.files_sha256:
        file = Path(run_dir) / name
        if file.suffix == ".parquet":
            tables[file.stem] = pd.read_parquet(file)
        elif file.suffix == ".csv":
            tables[file.stem] = pd.read_csv(file)
    return tables, manifest
