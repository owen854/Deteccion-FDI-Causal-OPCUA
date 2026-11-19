"""Ejecución de un escenario en modo en red: co-simulación con OPC UA real (RF-05, RF-22, RF-54).

1. Carga y valida la configuración (con los ajustes de la línea de comandos) y el escenario.
2. Crea la corrida: ``run_id``, carpeta ``data/raw/<run_id>``, bitácoras ``logs/<run_id>`` y la
   configuración efectiva (``config.yaml`` y ``scenario.yaml``).
3. Lanza los componentes como procesos (planta → gateway → controlador → monitor) y da la orden
   de inicio a la planta.
4. Mientras corre, recoge la verdad de terreno del plano de experimento en el historiador.
5. Al terminar (o ante un fallo o Ctrl+C) detiene todo en orden inverso, calcula el resumen
   (``summary.json``) y escribe el manifiesto con los SHA-256 (RF-26).

Implementado en la Fase 3; los ataques se agregan en la Fase 4.
"""

from __future__ import annotations

import time
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
) -> Path:
    """Ejecuta el escenario y devuelve la carpeta de la corrida (``data/raw/<run_id>``)."""
    import json

    from fdisim.common.config import deep_merge, load_config, load_scenario, load_yaml
    from fdisim.common.logging_setup import configure_logging
    from fdisim.data.historian import Historian
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
    }
    _dump_yaml(run_dir / "scenario.yaml", resolved)

    historian = Historian(run_dir, flush_every=2000, fmt=str(config["data"]["format"]))
    stats: dict[str, Any] = {}
    errors: list[str] = []
    state = {"finished": False}

    def record(event: Event) -> None:
        """Registra un evento sin interrumpir (se usa también durante la parada)."""
        if event.type is EventType.GROUND_TRUTH:
            historian.record_ground_truth(event.payload)
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
    )
    status = "completed"
    failure: BaseException | None = None
    say(
        f"Corrida {run_id}: {scenario.name}, {duration:.0f} s simulados a {scale:g}× "
        f"(≈ {duration / scale / 60:.1f} min), semilla {seed}, "
        f"{config['opcua']['security']['mode']} / {config['opcua']['security']['policy']}"
    )
    try:
        launcher.start_all(with_ui=with_ui)
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
        try:
            launcher.stop_all(on_event=record)
        except Exception:
            logger.exception("Error al detener los componentes")
        historian.close()
        launcher.hub.close()

    summary = summarize_network_run(run_dir, stats, config, scenario, seed, duration, status)
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
