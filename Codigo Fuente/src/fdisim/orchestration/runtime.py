"""Ejecución de un escenario en modo en red: co-simulación con OPC UA real (RF-05, RF-22, RF-54).

1. Carga y valida la configuración (con los ajustes de la línea de comandos) y el escenario.
2. Crea la corrida: ``run_id``, carpeta ``data/raw/<run_id>``, bitácoras ``logs/<run_id>`` y la
   configuración efectiva (``config.yaml`` y ``scenario.yaml``).
3. Lanza los componentes como procesos (planta → gateway → controlador → monitor) y da la orden
   de inicio a la planta.
4. Mientras corre, recoge del plano de experimento la verdad de terreno y los intervalos de
   ataque que reporta el gateway, y las salidas de los detectores en línea del monitor (Fase 6).
   Con una HMI (``--ui`` o ``--canal-hmi``) atiende además sus órdenes por el canal de
   experimento: estado, detecciones recientes, armar o desarmar ataques en caliente (RF-23),
   reconocer alarmas (RF-36) y detener la corrida (RF-48).
5. Al terminar (o ante un fallo o Ctrl+C) detiene todo en orden inverso, etiqueta las muestras
   y la verdad de terreno con los intervalos de ataque (RF-21), calcula el resumen
   (``summary.json``) y escribe el manifiesto con los SHA-256 (RF-26).

Implementado en la Fase 3; ataques y etiquetas en la Fase 4; detección en línea y HMI
como punto de entrada en las Fases 6 y 7.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from fdisim.common import paths
from fdisim.common.bus import CommandType, Event, EventType
from fdisim.common.types import RunManifest, RunMode


def _dump_yaml(path: Path, data: Mapping[str, Any]) -> str:
    import yaml

    text = yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return text


def write_run_inputs(
    run_dir: Path, config: Mapping[str, Any], scenario: Any, seed: int, duration: float
) -> str:
    """Guarda ``config.yaml`` y ``scenario.yaml`` (resuelto); devuelve el texto de la config."""
    from fdisim.common.config import load_yaml

    config_text = _dump_yaml(run_dir / "config.yaml", config)
    scenario_data = load_yaml(scenario.source) if scenario.source else {}
    scenario_data.pop("base", None)
    resolved = {
        **scenario_data,
        "name": scenario.name,
        "seed": seed,
        "duration_s": duration,
        "setpoint_profile": [{"t_s": t, "value_cm": v} for t, v in scenario.setpoint_profile],
        "disturbances": [dict(d) for d in scenario.disturbances],
        "attacks": [_attack_dict(a) for a in scenario.attacks],
    }
    _dump_yaml(run_dir / "scenario.yaml", resolved)
    return config_text


def _attack_dict(spec: Any) -> dict[str, Any]:
    stealth: dict[str, Any] = {"enabled": spec.stealth.enabled}
    if spec.stealth.envelope is not None:
        stealth["envelope"] = list(spec.stealth.envelope)
    if spec.stealth.max_rate_per_s is not None:
        stealth["max_rate_per_s"] = spec.stealth.max_rate_per_s
    return {
        "id": spec.attack_id,
        "type": spec.type.value,
        "targets": list(spec.targets),
        "start_s": spec.start_s,
        "duration_s": spec.duration_s,
        "params": dict(spec.params),
        "stealth": stealth,
    }


INTERACTIVE_DEFAULT_DURATION_S = 300.0


def interactive_attack(item: Mapping[str, Any], attack_id: str) -> Any:
    """Construye y valida un ataque armado desde la HMI (empieza «ahora»; RF-23)."""
    from fdisim.attacks.base import create_attack
    from fdisim.common.config import parse_attack

    data = {
        "id": attack_id,
        "start_s": 0.0,  # el gateway lo reemplaza por su tiempo simulado actual
        "duration_s": float(item.get("duration_s") or INTERACTIVE_DEFAULT_DURATION_S),
        **{k: v for k, v in item.items() if k not in ("id", "start_s", "duration_s")},
    }
    spec = parse_attack(data, 0)
    create_attack(spec)  # valida los parámetros antes de enviarlo
    return spec


def label_network_run(
    run_dir: Path, events: list[Any], start_epoch: float | None, time_scale: float, fmt: str
) -> None:
    """Agrega tiempo simulado y etiquetas a las muestras y a la verdad de terreno (RF-21)."""
    import pandas as pd

    from fdisim.data.labels import events_frame, label_ground_truth, label_samples

    def path(name: str) -> Path:
        return run_dir / f"{name}.{fmt}"

    def read(name: str) -> Any:
        return pd.read_parquet(path(name)) if fmt == "parquet" else pd.read_csv(path(name))

    def write(name: str, frame: Any) -> None:
        if fmt == "parquet":
            frame.to_parquet(path(name), index=False)
        else:
            frame.to_csv(path(name), index=False)

    if path("ground_truth").is_file():
        write("ground_truth", label_ground_truth(read("ground_truth"), events))
    if path("samples").is_file() and start_epoch is not None:
        samples = read("samples")
        sim_time = ((samples["source_ts"] - start_epoch) * time_scale).round(3)
        write("samples", label_samples(samples.assign(sim_time=sim_time), events))
    write("attacks", events_frame(events))


class PortInUseError(RuntimeError):
    """Un puerto OPC UA de la configuración ya está ocupado por otro proceso."""


def check_ports_free(config: Mapping[str, Any]) -> None:
    """Verifica antes de lanzar nada que los puertos de la planta y del gateway estén libres."""
    import socket

    opcua = config["opcua"]
    for name in ("plant_server", "gateway"):
        port = int(opcua[name]["port"])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((str(opcua["host"]), port))
            except OSError:
                raise PortInUseError(
                    f"El puerto {port} (opcua.{name}.port) ya está en uso: probablemente otra "
                    "corrida o el servidor de la prueba de concepto. Deténgalo o use otro puerto "
                    "con --config."
                ) from None


def run_scenario_network(
    scenario_path: Path,
    config_path: Path | None = None,
    seed: int | None = None,
    with_ui: bool = False,
    *,
    duration_s: float | None = None,
    time_scale: float | None = None,
    overrides: Mapping[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
    open_browser: bool = True,
    external_channel: bool = False,
) -> Path:
    """Ejecuta el escenario y devuelve la carpeta de la corrida (``data/raw/<run_id>``).

    Con ``external_channel`` la corrida atiende a una HMI que ya está corriendo (la que la
    lanzó con ``fdisim ui``): el canal de experimento usa la dirección y la clave que esa HMI
    dejó en las variables de entorno.
    """
    import json

    from fdisim.common.config import deep_merge, load_config, load_scenario
    from fdisim.common.experiment_channel import ExperimentServer
    from fdisim.common.logging_setup import configure_logging
    from fdisim.data.historian import Historian
    from fdisim.data.labels import merge_events
    from fdisim.data.storage import (
        finalize_run,
        git_commit,
        new_run_id,
        package_versions,
        sha256_text,
    )
    from fdisim.orchestration.launcher import START_ORDER, Component, Launcher
    from fdisim.orchestration.run_summary import summarize_network_run

    extra: dict[str, Any] = dict(overrides or {})
    if time_scale is not None:
        extra = deep_merge(extra, {"simulation": {"time_scale": float(time_scale)}})
    config = load_config(config_path, extra).to_dict()
    scenario = load_scenario(scenario_path)
    seed = scenario.seed if seed is None else int(seed)
    duration = float(duration_s or scenario.duration_s)
    scale = float(config["simulation"]["time_scale"])
    publishing_ms = float(config["opcua"]["subscription"]["publishing_interval_ms"])
    check_ports_free(config)

    run_id = new_run_id(scenario.name)
    run_dir = paths.resolve(config.get("data", {}).get("raw_dir", paths.RAW_DIR)) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir = paths.resolve(config.get("logging", {}).get("dir", paths.LOGS_DIR))
    logger = configure_logging(
        "orchestrator", run_id, str(config.get("logging", {}).get("level", "INFO")), log_dir
    )
    say = progress or logger.info

    config_text = write_run_inputs(run_dir, config, scenario, seed, duration)
    fmt = str(config["data"]["format"])
    historian = Historian(run_dir, flush_every=2000, fmt=fmt)
    stats: dict[str, Any] = {}
    errors: list[str] = []
    attack_events: list[Any] = []
    state: dict[str, Any] = {"finished": False, "sim_time": 0.0, "stop": False}
    # Salidas de los detectores en línea para la HMI (RF-49): búfer circular con secuencia.
    detections: deque[tuple[int, dict[str, Any]]] = deque(maxlen=6000)
    alarm_log: dict[str, dict[str, Any]] = {}
    acknowledged: set[str] = set()
    seq = itertools.count(1)
    lock = threading.Lock()

    def record(event: Event) -> None:
        """Registra un evento sin interrumpir (se usa también durante la parada)."""
        if event.type is EventType.GROUND_TRUTH:
            historian.record_ground_truth(event.payload)
            state["sim_time"] = event.payload.sim_time
        elif event.type is EventType.ATTACK:
            attack_events.append(event.payload)
            item = event.payload
            when = "termina" if item.t_end is not None else "inicia"
            say(
                f"Ataque {item.attack_id} ({item.type.value} sobre {','.join(item.targets)}) "
                f"{when} en t = {item.t_end if item.t_end is not None else item.t_start:.1f} s"
            )
        elif event.type is EventType.DETECTION:
            with lock:
                detections.append((next(seq), event.payload))
                for alarm in event.payload.get("alarms", []):
                    alarm_log[alarm["alarm_id"]] = alarm
        elif event.type is EventType.FINISHED:
            stats[event.source] = event.payload
            state["finished"] = True
        elif event.type is EventType.STATS:
            stats[event.source] = event.payload
        elif event.type is EventType.ERROR:
            errors.append(f"{event.source}: {event.payload}")
            logger.error("Fallo en %s: %s", event.source, event.payload)

    def handle(event: Event) -> None:
        record(event)
        if event.type is EventType.ERROR:
            raise RuntimeError(f"Fallo en {event.source}: {event.payload}")

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    launcher = Launcher(
        run_id,
        str(config_path or paths.DEFAULT_CONFIG),
        str(scenario_path),
        config=config,
        seed=seed,
        duration_s=duration,
        run_dir=run_dir,
        log_dir=log_dir,
        logger=logger,
        open_browser=open_browser,
    )
    counter = itertools.count(1)

    def experiment_request(message: dict[str, Any]) -> dict[str, Any]:
        """Órdenes de la HMI (otro hilo): se reenvían al gateway por el plano de experimento."""
        command = message.get("cmd")
        if command == "detections":
            since = int(message.get("since", 0))
            with lock:
                items = [{"seq": n, **item} for n, item in detections if n > since]
                last = detections[-1][0] if detections else since
            return {"ok": True, "seq": last, "items": items[-2000:]}
        if command == "ack":
            acknowledged.add(str(message.get("alarm_id")))
            return {"ok": True}
        if command == "stop":
            state["stop"] = True
            logger.warning("Parada solicitada desde la HMI")
            return {"ok": True}
        if command == "status":
            with lock:
                alarms = [
                    {**a, "acknowledged": a["alarm_id"] in acknowledged}
                    for a in list(alarm_log.values())[-200:]
                ]
            return {
                "ok": True,
                "run_id": run_id,
                "mode": "network",
                "time_scale": scale,
                "duration_s": duration,
                "alarms": alarms,
                "scenario": scenario.name,
                "sim_time": state["sim_time"],
                "finished": state["finished"],
                "scenario_attacks": [_attack_dict(a) for a in scenario.attacks],
                "events": [
                    {
                        "attack_id": e.attack_id,
                        "type": e.type.value,
                        "targets": list(e.targets),
                        "t_start": e.t_start,
                        "t_end": e.t_end,
                        "params": dict(e.params),
                    }
                    for e in merge_events(list(attack_events))
                ],
            }
        if command == "arm":
            spec = interactive_attack(message.get("attack") or {}, f"HMI-{next(counter)}")
            launcher.send(Component.GATEWAY, CommandType.ARM_ATTACK, spec=spec, start_now=True)
            logger.warning("Ataque %s armado desde la HMI", spec.attack_id)
            return {"ok": True, "attack_id": spec.attack_id}
        if command == "disarm":
            attack_id = str(message.get("attack_id"))
            launcher.send(Component.GATEWAY, CommandType.DISARM_ATTACK, attack_id=attack_id)
            return {"ok": True, "attack_id": attack_id}
        return {"ok": False, "error": f"Comando desconocido: {command}"}

    if external_channel:
        channel = ExperimentServer.from_environment(experiment_request)
    else:
        channel = ExperimentServer(experiment_request) if with_ui else None
    status = "completed"
    failure: BaseException | None = None
    say(
        f"Corrida {run_id}: {scenario.name}, {duration:.0f} s simulados a {scale:g}× "
        f"(≈ {duration / scale / 60:.1f} min), semilla {seed}, "
        f"{config['opcua']['security']['mode']} / {config['opcua']['security']['policy']}"
    )
    try:
        if channel is not None:
            channel.start()
        launcher.start_all(
            with_ui=with_ui, ui_env=channel.environment() if channel is not None else None
        )
        say("Componentes listos: " + " → ".join(c.value for c in START_ORDER))
        for event in launcher.backlog:
            handle(event)
        launcher.backlog.clear()
        launcher.send(Component.PLANT_SERVER, CommandType.START)
        wall_total = duration / scale
        deadline = time.perf_counter() + wall_total + 120.0
        t0 = time.perf_counter()
        next_report = 0.1
        while not state["finished"]:
            if state["stop"]:
                status = "stopped"
                say("Corrida detenida desde la HMI")
                break
            for event in launcher.hub.drain(0.5):
                handle(event)
            dead = launcher.dead_components()
            if dead:
                raise RuntimeError(f"Componentes detenidos inesperadamente: {', '.join(dead)}")
            if time.perf_counter() > deadline:
                raise TimeoutError("La planta no terminó en el tiempo esperado")
            fraction = (time.perf_counter() - t0) / wall_total
            if fraction >= next_report and next_report < 1.0:
                say(
                    f"Progreso: {100 * next_report:.0f} % "
                    f"({historian.counts['ground_truth']} pasos)"
                )
                next_report += 0.1
        # Margen para que las últimas notificaciones en tránsito lleguen al monitor.
        grace = time.perf_counter() + max(1.0, 5 * publishing_ms / 1000.0)
        while time.perf_counter() < grace:
            for event in launcher.hub.drain(0.1):
                handle(event)
    except KeyboardInterrupt as exc:
        status, failure = "interrupted", exc
        logger.warning("Corrida interrumpida por el usuario")
    except Exception as exc:
        status, failure = "failed", exc
        logger.exception("La corrida falló")
    finally:
        if channel is not None:
            channel.close()
        try:
            launcher.stop_all(on_event=record)
        except Exception:
            logger.exception("Error al detener los componentes")
        historian.close()
        launcher.hub.close()

    events = merge_events(attack_events)
    plant_stats = stats.get("plant_server") or {}
    label_network_run(run_dir, events, plant_stats.get("start_epoch"), scale, fmt)
    summary = summarize_network_run(
        run_dir, stats, config, scenario, seed, duration, status, events
    )
    summary["errors"] = errors
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    manifest = RunManifest(
        run_id=run_id,
        scenario=scenario.name,
        seed=seed,
        mode=RunMode.NETWORK,
        started_at=started_at,
        git_commit=git_commit(),
        config_sha256=sha256_text(config_text),
        package_versions=package_versions(),
    )
    finalize_run(run_dir, manifest)
    say(f"Corrida guardada en {run_dir} ({status})")
    if failure is not None:
        raise failure
    return run_dir
