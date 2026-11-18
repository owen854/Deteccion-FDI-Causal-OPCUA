"""Rutas del proyecto (raíz, configuración, datos, resultados).

Todas las rutas se resuelven respecto a la carpeta «Codigo Fuente» para que los
comandos funcionen igual desde cualquier directorio de trabajo.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
CONFIG_DIR: Path = PROJECT_ROOT / "config"
SCENARIOS_DIR: Path = CONFIG_DIR / "scenarios"
CAMPAIGNS_DIR: Path = CONFIG_DIR / "campaigns"
DEFAULT_CONFIG: Path = CONFIG_DIR / "default.yaml"
CERTS_DIR: Path = PROJECT_ROOT / "certs"
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
PROCESSED_DIR: Path = DATA_DIR / "processed"
MODELS_DIR: Path = DATA_DIR / "models"
RESULTS_DIR: Path = PROJECT_ROOT / "results"
LOGS_DIR: Path = PROJECT_ROOT / "logs"


def resolve(path: str | Path) -> Path:
    """Devuelve ``path`` absoluto; las rutas relativas se interpretan desde PROJECT_ROOT."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p
