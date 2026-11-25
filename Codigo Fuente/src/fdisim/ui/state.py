"""Estado compartido de la HMI: últimos valores, tendencias, detecciones, alarmas y corrida.

Lo actualizan el enlace OPC UA de la HMI (``ui.link``, valores del proceso) y el gestor de
corridas (``ui.run_manager``, salidas de los detectores en línea y estado de la corrida); lo
leen las páginas en cada refresco (``ui.refresh_hz``). Las tendencias se guardan
submuestreadas y en búferes circulares, para cumplir RNF-05 (memoria acotada) y no saturar el
navegador.

Implementado en la Fase 3 (HMI v0); detecciones, alarmas y resultados en la Fase 7.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdisim.common.types import SP_102, Alarm, Sample

CLOCK_TAG = "SIM.TIME"  # se publica en cada paso
HOLD_TAGS = (SP_102,)
DETECTION_POINTS = 4000  # 2000 s de detecciones a 0,5 s


@dataclass(slots=True)
class UiState:
    max_points: int = 1200  # 10 min con un punto cada 0,5 s
    trend_step_s: float = 0.5
    trends: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    scores: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    alarms: deque[Alarm] = field(default_factory=lambda: deque(maxlen=500))
    latest: dict[str, Sample] = field(default_factory=dict)
    connection_status: dict[str, str] = field(default_factory=dict)
    running_scenario: str | None = None
    messages: deque[str] = field(default_factory=lambda: deque(maxlen=50))
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    # --- detección (Fase 7) ------------------------------------------------------------
    det_scores: dict[str, dict[str, deque[tuple[float, float]]]] = field(default_factory=dict)
    det_alarm: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    det_latest: dict[str, dict[str, Any]] = field(default_factory=dict)
    alarm_log: dict[str, dict[str, Any]] = field(default_factory=dict)
    acknowledged: set[str] = field(default_factory=set)
    attack_events: list[dict[str, Any]] = field(default_factory=list)
    scenario_attacks: list[dict[str, Any]] = field(default_factory=list)
    run_status: dict[str, Any] = field(default_factory=dict)
    detection_source: str = "sin datos"
    last_run_dir: str | None = None

    # ------------------------------------------------------------------ proceso (OPC UA)
    def push_trend(self, tag: str, t: float, value: float) -> None:
        buf = self.trends.setdefault(tag, deque(maxlen=self.max_points))
        if buf and t - buf[-1][0] < self.trend_step_s:
            return
        buf.append((t, value))

    def push_sample(self, sample: Sample) -> None:
        """Registra una muestra OPC UA (último valor y, si es numérica, su tendencia).

        Las variables que solo cambian por escritura (consigna) se repiten en cada paso del
        tiempo simulado, para que su tendencia se dibuje como una línea continua.
        """
        self.latest[sample.tag] = sample
        if math.isfinite(sample.received_ts) and math.isfinite(sample.source_ts):
            self.latencies_ms.append(1000.0 * (sample.received_ts - sample.source_ts))
        if sample.status == "Good":
            self.push_trend(sample.tag, sample.source_ts, sample.value)
        if sample.tag == CLOCK_TAG:
            for tag in HOLD_TAGS:
                held = self.latest.get(tag)
                if held is not None and held.status == "Good":
                    self.push_trend(tag, sample.source_ts, held.value)

    def value(self, tag: str, default: float = float("nan")) -> float:
        sample = self.latest.get(tag)
        return sample.value if sample is not None else default

    # ------------------------------------------------------------------ detección
    def reset_run(self) -> None:
        """Limpia lo propio de una corrida (al iniciar otra desde la HMI)."""
        self.det_scores.clear()
        self.det_alarm.clear()
        self.det_latest.clear()
        self.alarm_log.clear()
        self.acknowledged.clear()
        self.attack_events = []
        self.scenario_attacks = []
        self.run_status = {}
        self.detection_source = "sin datos"

    def push_detection(self, item: dict[str, Any]) -> None:
        """Salida de un detector en línea (la trae el gestor de corridas del orquestador)."""
        kind = str(item["detector"])
        t = float(item["t"])
        series = self.det_scores.setdefault(kind, {})
        for name, value in item.get("scores", {}).items():
            if value is None or not math.isfinite(value):
                continue
            series.setdefault(name, deque(maxlen=DETECTION_POINTS)).append((t, float(value)))
        self.det_alarm.setdefault(kind, deque(maxlen=DETECTION_POINTS)).append(
            (t, 1.0 if item.get("alarm") else 0.0)
        )
        self.det_latest[kind] = item
        for alarm in item.get("alarms", []):
            self.alarm_log[alarm["alarm_id"]] = dict(alarm)
        self.detection_source = "corrida en curso"

    def update_status(self, status: dict[str, Any]) -> None:
        self.run_status = status
        self.attack_events = list(status.get("events", []))
        self.scenario_attacks = list(status.get("scenario_attacks", []))
        for alarm in status.get("alarms", []):
            current = self.alarm_log.get(alarm["alarm_id"], {})
            self.alarm_log[alarm["alarm_id"]] = {**current, **alarm}
            if alarm.get("acknowledged"):
                self.acknowledged.add(alarm["alarm_id"])

    def active_alarm(self, kind: str) -> dict[str, Any] | None:
        latest = self.det_latest.get(kind)
        if not latest or not latest.get("alarm"):
            return None
        return latest

    def load_run_results(self, run_dir: str | Path) -> bool:
        """Carga las detecciones guardadas de una corrida (``<run_dir>/detection``)."""
        import pandas as pd

        run_dir = Path(run_dir)
        folder = run_dir / "detection"
        if not (folder / "causal.parquet").is_file():
            return False
        self.reset_run()
        for kind in ("causal", "threshold"):
            path = folder / f"{kind}.parquet"
            if not path.is_file():
                continue
            frame = pd.read_parquet(path)
            t = frame["sim_time"].to_numpy(float)
            skip = {"run_id", "sim_time", "alarm", "suspected", "triggered", "processing_ms"}
            series = self.det_scores.setdefault(kind, {})
            for column in frame.columns:
                if column in skip or column.startswith("ewma:"):
                    continue
                values = frame[column].to_numpy(float)
                series[column] = deque(
                    (
                        (float(a), float(b))
                        for a, b in zip(t, values, strict=True)
                        if math.isfinite(b)
                    ),
                    maxlen=DETECTION_POINTS,
                )
            self.det_alarm[kind] = deque(
                zip(t.tolist(), frame["alarm"].astype(float).tolist(), strict=True),
                maxlen=DETECTION_POINTS,
            )
            last = frame.iloc[-1]
            self.det_latest[kind] = {
                "t": float(last["sim_time"]),
                "alarm": bool(last["alarm"]),
                "suspected": last["suspected"] or None,
                "triggered": [],
            }
        alarms_path = folder / "alarms.csv"
        if alarms_path.is_file():
            alarms = pd.read_csv(alarms_path, dtype={"variables": str, "suspected_tag": str})
            for row in alarms.to_dict("records"):
                variables = row.get("variables")
                row["variables"] = (
                    [v for v in variables.split(",") if v] if isinstance(variables, str) else []
                )
                row["suspected_tag"] = (
                    row["suspected_tag"] if isinstance(row.get("suspected_tag"), str) else ""
                )
                t_end = row.get("t_end")
                row["t_end"] = float(t_end) if t_end is not None and t_end == t_end else None
                self.alarm_log[str(row["alarm_id"])] = row
        attacks = next(
            (
                run_dir / f"attacks.{ext}"
                for ext in ("parquet", "csv")
                if (run_dir / f"attacks.{ext}").is_file()
            ),
            None,
        )
        if attacks is not None:
            frame = (
                pd.read_parquet(attacks) if attacks.suffix == ".parquet" else pd.read_csv(attacks)
            )
            self.attack_events = [
                {
                    "attack_id": str(r["attack_id"]),
                    "type": str(r["type"]),
                    "targets": str(r["targets"]).split(","),
                    "t_start": float(r["t_start"]),
                    "t_end": float(r["t_end"]) if r["t_end"] == r["t_end"] else None,
                }
                for r in frame.to_dict("records")
            ]
        self.detection_source = f"corrida guardada {run_dir.name}"
        self.last_run_dir = str(run_dir)
        return True
