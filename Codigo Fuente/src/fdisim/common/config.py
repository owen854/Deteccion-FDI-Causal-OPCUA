"""Carga y validación de la configuración YAML (RF-53).

Estructura: ``config/default.yaml`` (global) + escenario (``config/scenarios``) que puede
heredar de otro con la clave ``base``. La validación rechaza valores físicamente inválidos
indicando el campo erróneo (criterio de aceptación de RF-02 y RF-53).

Fase de implementación: Fase 3 (Documento 03). Dependencia prevista: PyYAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdisim.common.types import AttackSpec


class ConfigError(ValueError):
    """Configuración inválida; el mensaje indica la ruta del campo (p. ej. plant.tank1.area_cm2)."""


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Escenario ya resuelto (herencia aplicada) y validado."""

    name: str
    description: str
    duration_s: float
    seed: int
    setpoint_profile: tuple[tuple[float, float], ...]
    disturbances: tuple[Mapping[str, Any], ...] = ()
    attacks: tuple[AttackSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Configuración global. Cada sección se mantiene como mapeo validado."""

    simulation: Mapping[str, Any]
    plant: Mapping[str, Any]
    control: Mapping[str, Any]
    opcua: Mapping[str, Any]
    detection: Mapping[str, Any]
    data: Mapping[str, Any]
    ui: Mapping[str, Any]
    logging: Mapping[str, Any] = field(default_factory=dict)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Lee un archivo YAML y devuelve un diccionario."""
    raise NotImplementedError("Fase 3 — RF-53: lectura de YAML (PyYAML)")


def load_config(path: str | Path | None = None) -> AppConfig:
    """Carga ``default.yaml`` (o ``path``), aplica valores por defecto y valida."""
    raise NotImplementedError("Fase 3 — RF-53: carga y validación de la configuración global")


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Carga un escenario, resuelve ``base`` y convierte los ataques en ``AttackSpec``."""
    raise NotImplementedError("Fase 4 — RF-20/RF-22: carga de escenarios")


def validate(config: Mapping[str, Any]) -> None:
    """Valida rangos físicos y valores permitidos; lanza ``ConfigError`` con la ruta del campo."""
    raise NotImplementedError("Fase 3 — RF-02/RF-53: validación de esquema")
