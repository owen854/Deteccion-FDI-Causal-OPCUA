"""Gestor de corridas de la HMI: el aplicativo completo con un solo comando (RF-48, RNF-14).

Con ``fdisim ui`` (o ``fdisim`` a secas) la HMI es el punto de entrada del aplicativo:

- **Preparación automática** (``prepare``): crea los certificados que falten y, si no hay
  modelo causal, genera el dataset y entrena el modelo (incluida la calibración de los
  detectores) en segundo plano, mostrando el avance en la página de experimentos.
- **Corridas** (``start`` y ``stop``): lanza ``fdisim run`` como subproceso, en red o offline,
  con la misma configuración que la HMI. En red, la HMI elige la dirección y la clave del canal
  de experimento y se las pasa a la corrida (``--canal-hmi``); así puede pedir el estado, las
  detecciones, armar ataques y detener la corrida de forma ordenada.
- **Flujo de detecciones** (``poll``): trae del orquestador las salidas recientes de los
  detectores en línea y las vuelca en ``UiState`` (RF-49).

Si la HMI la lanzó una corrida (``fdisim run --ui``), el gestor solo se conecta a esa corrida.

Implementado en la Fase 7.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdisim.common import paths
from fdisim.common.experiment_channel import (
    ExperimentClient,
    channel_environment,
    local_channel,
)
from fdisim.ui.state import UiState

SAVED = re.compile(r"Corrida (?:offline )?guardada en (.+?)(?: \(\w+\))?$")


def scenario_catalog() -> list[dict[str, Any]]:
    """Escenarios disponibles (``config/scenarios``) con su descripción y duración."""
    import yaml

    out = []
    for path in sorted(paths.SCENARIOS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        out.append(
            {
                "path": str(path),
                "name": str(data.get("name", path.stem)),
                "description": str(data.get("description", "")),
                "duration_s": float(data.get("duration_s", 0) or 0),
                "attacks": len(data.get("attacks") or []),
            }
        )
    return out


class RunManager:
    def __init__(
        self,
        config: Mapping[str, Any],
        state: UiState,
        config_path: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.config_path = config_path or str(paths.DEFAULT_CONFIG)
        self.logger = logger or logging.getLogger("fdisim.hmi.corridas")
        self.output: deque[str] = deque(maxlen=400)
        self.process: subprocess.Popen | None = None
        self.mode: str | None = None
        self.scenario: str | None = None
        self.last_run_dir: Path | None = None
        self.preparing = False
        self.prepare_status = "pendiente"
        self._since = 0
        # ¿Esta HMI la lanzó una corrida (fdisim run --ui)? Entonces solo observa esa corrida.
        self.external = ExperimentClient.from_environment()
        self.client: ExperimentClient | None = self.external

    # ------------------------------------------------------------------ estado
    @property
    def owns_runs(self) -> bool:
        return self.external is None

    @property
    def running(self) -> bool:
        if self.external is not None:
            return True
        return self.process is not None and self.process.poll() is None

    @property
    def model_ready(self) -> bool:
        from fdisim.detection.pipeline import model_available

        return model_available(self.config)

    def _say(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        self.output.append(line)
        match = SAVED.search(line)
        if match:
            self.last_run_dir = Path(match.group(1).strip())
            self.state.last_run_dir = str(self.last_run_dir)

    # ------------------------------------------------------------------ preparación
    def prepare(self) -> None:
        """Certificados y modelo causal listos (en un hilo; no bloquea la HMI)."""
        if self.preparing or not self.owns_runs:
            return
        self.preparing = True
        threading.Thread(target=self._prepare, name="preparacion", daemon=True).start()

    def _prepare(self) -> None:
        try:
            from fdisim.opcua.security import setup_pki

            created = setup_pki(self.config["opcua"]["security"].get("certs_dir", "certs"))
            if created["created"]:
                self._say(f"Certificados creados: {', '.join(created['created'])}")
            if not self.model_ready:
                self.prepare_status = "generando el dataset (primera vez, unos minutos)"
                self._run_blocking(["dataset"])
                self.prepare_status = "entrenando el modelo causal y calibrando los detectores"
                self._run_blocking(
                    ["train", "--data", str(paths.PROCESSED_DIR / "v1" / "train.parquet")]
                )
            self.prepare_status = "listo" if self.model_ready else "sin modelo causal"
        except Exception as exc:
            self.prepare_status = f"error: {exc}"
            self.logger.exception("Falló la preparación del aplicativo")
        finally:
            self.preparing = False

    def _command(self, args: list[str]) -> list[str]:
        return [sys.executable, "-X", "utf8", "-m", "fdisim", *args, "--config", self.config_path]

    def _run_blocking(self, args: list[str]) -> None:
        proc = subprocess.Popen(
            self._command(args),
            cwd=paths.PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            self._say(line)
        if proc.wait() != 0:
            raise RuntimeError(f"fdisim {args[0]} terminó con código {proc.returncode}")

    # ------------------------------------------------------------------ corridas
    def start(
        self,
        scenario_path: str,
        mode: str = "network",
        duration_s: float | None = None,
        time_scale: float | None = None,
        seed: int | None = None,
    ) -> str:
        """Lanza la corrida; devuelve un mensaje para el usuario."""
        if not self.owns_runs:
            return "Esta HMI pertenece a una corrida lanzada desde la consola"
        if self.running:
            return "Ya hay una corrida en curso: deténgala primero"
        if self.preparing:
            return "Espere a que termine la preparación del aplicativo"
        args = ["run", "--scenario", scenario_path, "--mode", mode]
        if duration_s:
            args += ["--duracion", f"{float(duration_s):g}"]
        if seed is not None:
            args += ["--seed", str(int(seed))]
        env = dict(os.environ)
        if mode == "network":
            if time_scale:
                args += ["--escala", f"{float(time_scale):g}"]
            address, key = local_channel()
            args.append("--canal-hmi")
            env.update(channel_environment(address, key))
            self.client = ExperimentClient(address, key)
        else:
            self.client = None
        self.output.clear()
        self.state.reset_run()
        self._since = 0
        self.mode, self.scenario = mode, Path(scenario_path).stem
        self.state.running_scenario = self.scenario
        self.process = subprocess.Popen(
            self._command(args),
            cwd=paths.PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=self._pump, args=(self.process,), daemon=True).start()
        self.logger.info("Corrida lanzada desde la HMI: %s (%s)", self.scenario, mode)
        return (
            f"Corrida «{self.scenario}» iniciada ({'en red' if mode == 'network' else 'offline'})"
        )

    def _pump(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self._say(line)
        proc.wait()
        self._say(f"La corrida terminó (código {proc.returncode})")
        if self.last_run_dir is not None:
            self.state.load_run_results(self.last_run_dir)

    def stop(self) -> str:
        if not self.running:
            return "No hay una corrida en curso"
        if self.mode == "network" or self.external is not None:
            reply = self.client.stop() if self.client is not None else {"ok": False}
            if reply.get("ok"):
                return "Parada solicitada: la corrida se cierra y guarda sus datos"
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            return "Corrida terminada"
        return "No se pudo detener la corrida"

    # ------------------------------------------------------------------ datos en vivo
    def status(self) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "error": "Sin corrida en red activa"}
        return self.client.status()

    def poll(self) -> None:
        """Trae las detecciones nuevas del orquestador y el estado de la corrida."""
        if self.client is None or not self.running:
            return
        reply = self.client.detections(self._since)
        if reply.get("ok"):
            self._since = int(reply.get("seq", self._since))
            for item in reply.get("items", []):
                self.state.push_detection(item)
        status = self.client.status()
        if status.get("ok"):
            self.state.update_status(status)

    def acknowledge(self, alarm_id: str) -> None:
        self.state.acknowledged.add(alarm_id)
        if self.client is not None:
            self.client.acknowledge(alarm_id)
