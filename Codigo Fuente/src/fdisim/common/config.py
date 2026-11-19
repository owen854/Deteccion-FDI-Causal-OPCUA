"""Carga y validación de la configuración YAML (RF-53).

Estructura: ``config/default.yaml`` (global) + escenario (``config/scenarios``) que puede
heredar de otro con la clave ``base`` (las claves de primer nivel del escenario reemplazan a
las de la base). Los errores indican la ruta del campo (criterio de aceptación de RF-02 y
RF-53); los rangos físicos se validan al construir cada componente (``from_config``).

``load_yaml`` y ``load_scenario`` se implementaron en la Fase 2; ``load_config`` (con valores
por defecto tomados de ``default.yaml``) y ``validate``, en la Fase 3.
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

    def to_dict(self) -> dict[str, Any]:
        """Configuración efectiva como diccionario (se guarda con cada corrida, RF-26)."""
        return {name: _plain(getattr(self, name)) for name in self.__dataclass_fields__}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


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


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Combina dos mapeos; los valores de ``override`` reemplazan a los de ``base``."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(
    path: str | Path | None = None, overrides: Mapping[str, Any] | None = None
) -> AppConfig:
    """Carga ``default.yaml``, le superpone ``path`` y ``overrides`` (valores por defecto) y valida.

    Un archivo propio solo necesita las claves que cambia, p. ej. ``simulation.time_scale``.
    """
    from fdisim.common import paths

    data = load_yaml(paths.DEFAULT_CONFIG)
    if path is not None and Path(path).resolve() != paths.DEFAULT_CONFIG.resolve():
        data = deep_merge(data, load_yaml(path))
    if overrides:
        data = deep_merge(data, overrides)
    validate(data)
    return AppConfig(**{name: data.get(name, {}) for name in AppConfig.__dataclass_fields__})


def _number(
    cfg: Mapping[str, Any],
    key: str,
    where: str,
    *,
    minimum: float | None = None,
    positive: bool = False,
    integer: bool = False,
) -> float:
    if key not in cfg:
        raise ConfigError(f"{where}.{key}: campo obligatorio")
    value = cfg[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{where}.{key}: debe ser numérico (valor: {value!r})")
    if integer and int(value) != value:
        raise ConfigError(f"{where}.{key}: debe ser entero (valor: {value})")
    if positive and value <= 0:
        raise ConfigError(f"{where}.{key}: debe ser positivo (valor: {value})")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where}.{key}: debe ser ≥ {minimum} (valor: {value})")
    return float(value)


def _choice(cfg: Mapping[str, Any], key: str, where: str, allowed: tuple[str, ...]) -> str:
    value = cfg.get(key)
    if value not in allowed:
        raise ConfigError(f"{where}.{key}: use {list(allowed)} (valor: {value!r})")
    return str(value)


def _section(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = config.get(name)
    if not isinstance(section, Mapping):
        raise ConfigError(f"{name}: sección obligatoria")
    return section


def _validate_simulation(sim: Mapping[str, Any]) -> None:
    _number(sim, "dt_s", "simulation", positive=True)
    _number(sim, "time_scale", "simulation", positive=True)
    _number(sim, "duration_s", "simulation", positive=True)
    _number(sim, "seed", "simulation", minimum=0, integer=True)
    _choice(sim, "mode", "simulation", ("network", "offline"))
    _choice(sim, "integrator", "simulation", ("solve_ivp", "rk4"))


def _validate_plant(plant: Mapping[str, Any]) -> None:
    from fdisim.process.actuators import PumpParams
    from fdisim.process.plant import SENSOR_RANGES
    from fdisim.process.sensors import SensorSpec
    from fdisim.process.two_tank_model import TwoTankParams

    for key in ("tank1", "tank2", "pump"):
        if not isinstance(plant.get(key), Mapping):
            raise ConfigError(f"plant.{key}: sección obligatoria")
    try:
        TwoTankParams.from_config(plant)
        PumpParams.from_config(plant["pump"])
        for tag, cfg in (plant.get("sensors") or {}).items():
            if tag not in SENSOR_RANGES:
                raise ConfigError(
                    f"plant.sensors.{tag}: sensor desconocido {sorted(SENSOR_RANGES)}"
                )
            SensorSpec.from_config(tag, cfg, SENSOR_RANGES[tag])
    except KeyError as exc:
        raise ConfigError(f"plant.{exc.args[0]}: campo obligatorio") from None


def _validate_control(
    control: Mapping[str, Any], sim: Mapping[str, Any], plant: Mapping[str, Any]
) -> None:
    from fdisim.common.types import LT_101, LT_102, P_101
    from fdisim.control.pid import PIDParams

    try:
        params = PIDParams.from_config(control)
    except KeyError as exc:
        raise ConfigError(f"control.{exc.args[0]}: campo obligatorio") from None
    _choice(control, "controlled_tag", "control", (LT_102, LT_101))
    _choice(control, "manipulated_tag", "control", (P_101,))
    ratio = params.ts_s / float(sim["dt_s"])
    if abs(ratio - round(ratio)) > 1e-9 or round(ratio) < 1:
        raise ConfigError(
            "control.ts_s: debe ser múltiplo entero de simulation.dt_s "
            f"({params.ts_s} / {sim['dt_s']})"
        )
    sp = _number(control, "setpoint_cm", "control", positive=True)
    h_max = float(plant["tank2"].get("max_height_cm", 0.0))
    if sp >= h_max:
        raise ConfigError(
            f"control.setpoint_cm: debe ser menor que la altura del tanque 2 ({sp} ≥ {h_max})"
        )


def _validate_host(host: Any, where: str) -> None:
    """RNF-11: solo localhost o direcciones privadas de una red de laboratorio aislada."""
    import ipaddress

    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(str(host))
    except ValueError:
        raise ConfigError(
            f"{where}: use una dirección IP o 'localhost' (valor: {host!r})"
        ) from None
    if not (address.is_loopback or address.is_private):
        raise ConfigError(
            f"{where}: solo se permite localhost o una red privada de laboratorio (RNF-11) "
            f"(valor: {host})"
        )


def _validate_opcua(opcua: Mapping[str, Any]) -> None:
    from fdisim.opcua.security import SecurityConfig

    _validate_host(opcua.get("host"), "opcua.host")
    ports: dict[int, str] = {}
    for name in ("plant_server", "gateway"):
        endpoint = opcua.get(name)
        if not isinstance(endpoint, Mapping):
            raise ConfigError(f"opcua.{name}: sección obligatoria")
        port = int(_number(endpoint, "port", f"opcua.{name}", integer=True, minimum=1024))
        if port > 65535:
            raise ConfigError(f"opcua.{name}.port: debe ser ≤ 65535 (valor: {port})")
        if port in ports:
            raise ConfigError(f"opcua.{name}.port: repetido con opcua.{ports[port]}.port ({port})")
        ports[port] = name
        if not str(endpoint.get("path", "")).startswith("/"):
            raise ConfigError(f"opcua.{name}.path: debe empezar por '/'")
    try:
        SecurityConfig.from_config(opcua.get("security") or {})
    except ValueError as exc:
        raise ConfigError(f"opcua.security: {exc}") from None
    sub = opcua.get("subscription") or {}
    _number(sub, "publishing_interval_ms", "opcua.subscription", positive=True)
    rec = opcua.get("reconnect") or {}
    initial = _number(rec, "initial_delay_s", "opcua.reconnect", positive=True)
    if _number(rec, "max_delay_s", "opcua.reconnect", positive=True) < initial:
        raise ConfigError("opcua.reconnect.max_delay_s: debe ser ≥ initial_delay_s")


def validate(config: Mapping[str, Any]) -> None:
    """Valida rangos físicos y valores permitidos; lanza ``ConfigError`` con la ruta del campo."""
    sim = _section(config, "simulation")
    _validate_simulation(sim)
    plant = _section(config, "plant")
    _validate_plant(plant)
    _validate_control(_section(config, "control"), sim, plant)
    _validate_opcua(_section(config, "opcua"))
    if "detection" in config:
        _number(_section(config, "detection"), "period_s", "detection", positive=True)
    if "data" in config:
        _choice(_section(config, "data"), "format", "data", ("parquet", "csv"))
    if "ui" in config:
        ui = _section(config, "ui")
        _validate_host(ui.get("host"), "ui.host")
        _number(ui, "port", "ui", integer=True, minimum=1024)
        _number(ui, "refresh_hz", "ui", positive=True)
    if "logging" in config:
        _choice(
            _section(config, "logging"), "level", "logging", ("DEBUG", "INFO", "WARNING", "ERROR")
        )
