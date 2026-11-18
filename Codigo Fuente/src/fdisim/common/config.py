"""Carga y validación de la configuración YAML (RF-53).

Estructura: ``config/default.yaml`` (global) + escenario (``config/scenarios``) que puede
heredar de otro con la clave ``base`` (las claves de primer nivel del escenario reemplazan a
las de la base). Los errores indican la ruta del campo (criterio de aceptación de RF-02 y
RF-53); los rangos físicos se validan al construir cada componente (``from_config``).

Implementado: ``load_yaml`` y ``load_scenario`` (Fase 2). Pendiente: ``load_config`` y
``validate`` con el esquema global completo (Fase 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdisim.common.types import PROCESS_TAGS, AttackSpec, AttackType, StealthSpec


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
    source: Path | None = None


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
    import yaml

    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"No existe el archivo de configuración: {p}")
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{p.name}: el contenido debe ser un mapeo YAML")
    return data


def _resolve_scenario(path: Path, seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    path = path.resolve()
    if path in seen:
        raise ConfigError(f"{path.name}: herencia circular en 'base'")
    data = load_yaml(path)
    base = data.pop("base", None)
    if base is None:
        return data
    merged = _resolve_scenario(path.parent / base, (*seen, path))
    merged.update(data)
    return merged


def _parse_attack(item: Mapping[str, Any], i: int) -> AttackSpec:
    where = f"attacks[{i}]"
    try:
        kind = AttackType(item["type"])
        targets = tuple(item["targets"])
        start, duration = float(item["start_s"]), float(item["duration_s"])
    except KeyError as exc:
        raise ConfigError(f"{where}.{exc.args[0]}: campo obligatorio") from None
    except ValueError:
        raise ConfigError(f"{where}.type: use {[t.value for t in AttackType]}") from None
    unknown = set(targets) - set(PROCESS_TAGS)
    if not targets or unknown:
        raise ConfigError(f"{where}.targets: etiquetas desconocidas {sorted(unknown) or '[]'}")
    if duration <= 0 or start < 0:
        raise ConfigError(f"{where}: start_s ≥ 0 y duration_s > 0")
    stealth_cfg = item.get("stealth") or {}
    envelope = stealth_cfg.get("envelope")
    stealth = StealthSpec(
        enabled=bool(stealth_cfg.get("enabled", False)),
        envelope=(float(envelope[0]), float(envelope[1])) if envelope else None,
        max_rate_per_s=stealth_cfg.get("max_rate_per_s"),
    )
    params = {k: float(v) for k, v in (item.get("params") or {}).items()}
    return AttackSpec(
        str(item.get("id", f"A{i + 1}")), kind, targets, start, duration, params, stealth
    )


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Carga un escenario, resuelve ``base`` y convierte los ataques en ``AttackSpec``."""
    p = Path(path)
    data = _resolve_scenario(p)
    duration = float(data.get("duration_s", 0))
    if duration <= 0:
        raise ConfigError(f"{p.name}.duration_s: debe ser positiva")
    profile = data.get("setpoint_profile") or []
    if not profile:
        raise ConfigError(f"{p.name}.setpoint_profile: se requiere al menos un punto")
    try:
        setpoints = tuple((float(s["t_s"]), float(s["value_cm"])) for s in profile)
    except KeyError as exc:
        raise ConfigError(f"{p.name}.setpoint_profile.{exc.args[0]}: campo obligatorio") from None
    attacks = tuple(_parse_attack(a, i) for i, a in enumerate(data.get("attacks") or []))
    return ScenarioConfig(
        name=str(data.get("name", p.stem)),
        description=str(data.get("description", "")),
        duration_s=duration,
        seed=int(data.get("seed", 0)),
        setpoint_profile=setpoints,
        disturbances=tuple(data.get("disturbances") or ()),
        attacks=attacks,
        source=p,
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    """Carga ``default.yaml`` (o ``path``), aplica valores por defecto y valida."""
    raise NotImplementedError("Fase 3 — RF-53: carga y validación de la configuración global")


def validate(config: Mapping[str, Any]) -> None:
    """Valida rangos físicos y valores permitidos; lanza ``ConfigError`` con la ruta del campo."""
    raise NotImplementedError("Fase 3 — RF-02/RF-53: validación de esquema")
