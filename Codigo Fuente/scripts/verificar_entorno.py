"""Verifica que el entorno cumple los requisitos de FDISim-OPCUA (RNF-19).

Uso::

    python scripts/verificar_entorno.py

Comprueba la versión de Python, las dependencias instaladas (con su versión) y la estructura
de carpetas. Devuelve código 0 si todo es correcto y 1 si falta algo obligatorio.
"""

from __future__ import annotations

import importlib.metadata as md
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (módulo importable, distribución en PyPI, uso)
DEPENDENCIES = [
    ("asyncua", "asyncua", "OPC UA"),
    ("cryptography", "cryptography", "seguridad OPC UA"),
    ("numpy", "numpy", "cálculo numérico"),
    ("scipy", "scipy", "simulación"),
    ("pandas", "pandas", "datos"),
    ("pyarrow", "pyarrow", "Parquet"),
    ("networkx", "networkx", "grafos"),
    ("statsmodels", "statsmodels", "Granger"),
    ("sklearn", "scikit-learn", "regresión y ROC"),
    ("tigramite", "tigramite", "PCMCI"),
    ("nicegui", "nicegui", "HMI web"),
    ("plotly", "plotly", "gráficas"),
    ("matplotlib", "matplotlib", "figuras"),
    ("yaml", "PyYAML", "configuración"),
]
DEV_DEPENDENCIES = [("pytest", "pytest", "pruebas"), ("ruff", "ruff", "estilo")]
FOLDERS = [
    "config/scenarios",
    "config/campaigns",
    "certs",
    "data/raw",
    "data/processed",
    "data/models",
    "results",
    "logs",
    "src/fdisim",
    "tests",
]


def check(deps: list[tuple[str, str, str]]) -> list[str]:
    missing = []
    for module, dist, use in deps:
        if importlib.util.find_spec(module) is None:
            print(f"  [FALTA] {dist:<14} ({use})")
            missing.append(dist)
        else:
            try:
                version = md.version(dist)
            except md.PackageNotFoundError:
                version = "?"
            print(f"  [OK]    {dist:<14} {version:<10} ({use})")
    return missing


def main() -> int:
    ok = True
    v = sys.version_info
    print(f"Python {v.major}.{v.minor}.{v.micro} — {sys.executable}")
    if v < (3, 11):
        print("  [ERROR] Se requiere Python >= 3.11 (recomendado 3.12).")
        ok = False
    elif v[:2] != (3, 12):
        print(
            "  [AVISO] Versión recomendada: 3.12 (algunas bibliotecas científicas tardan en "
            "soportar versiones más nuevas)."
        )

    print("\nDependencias de ejecución:")
    missing = check(DEPENDENCIES)
    print("\nDependencias de desarrollo:")
    missing_dev = check(DEV_DEPENDENCIES)

    print("\nEstructura de carpetas:")
    for folder in FOLDERS:
        exists = (ROOT / folder).is_dir()
        print(f"  [{'OK' if exists else 'FALTA'}] {folder}")
        ok &= exists

    if missing or missing_dev:
        print('\nInstale lo que falta con:  pip install -e ".[dev]"')
    ok &= not missing
    print("\nResultado:", "entorno listo" if ok else "entorno incompleto")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
