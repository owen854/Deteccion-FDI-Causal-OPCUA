"""Detector de inconsistencias causales (RF-33, RF-34, RF-36, RF-37; OE3).

Flujo por muestra de la rejilla de detección:

1. **Residuos** (``ResidualComputer``): a un paso para LT-101, LT-102, FT-101 y P-101, y del
   gemelo causal en dos horizontes para los niveles; normalizados con las estadísticas de
   entrenamiento (RF-33).
2. **Decisión** (RF-34): umbral asimétrico sobre cada residuo; además CUSUM bilateral y EWMA
   sobre los residuos a un paso (los del gemelo ya integran la historia). Los límites se
   calibran en validación para que el FPR combinado, ya con la retención de alarmas, no supere
   ``detection.decision.target_fpr`` (``fit``). El CUSUM se satura en 1,5·h para que, al
   terminar un ataque, vuelva bajo su límite en segundos y no prolongue la alarma.
3. **Retención** de ``alarm_hold_s`` y **alarmas** con instante, variables implicadas, tipo de
   inconsistencia, severidad y estado (RF-36).
4. **Identificación** de la variable comprometida por la firma de residuos sobre el grafo
   (RF-37, ``detection.isolation``).

Dos decisiones de diseño, tomadas al probar en red (Fase 6):

- El residuo a un paso de P-101 (ley PI) se calcula y se muestra, pero **no decide**: el
  controlador muestrea los niveles en su propio instante y no en la rejilla, así que en red su
  residuo refleja el ruido de dos muestras distintas (z ≈ ±100 con los límites de los datos
  offline, donde ambos instantes coinciden). Ninguna firma de identificación lo necesita.
- **Arranque:** no se emiten alarmas hasta tener la historia del horizonte más largo del gemelo
  (60 s), porque al inicio de una corrida en red el controlador sale de su estado inicial.

La verificación estructural por ventanas (RF-35, prioridad «Debería») queda diferida: en esta
versión el residuo del gemelo en horizonte cubre el caso del replay con excitación (cambio de
consigna o perturbación durante el ataque).

Implementado en la Fase 6.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common.types import AlarmKind, DetectorKind
from fdisim.detection.base import AlarmTracker, DetectionResult, Detector, register_detector
from fdisim.detection.decision import (
    AlarmLatch,
    Cusum,
    Ewma,
    calibrate_limits,
    cusum_statistic,
    ewma_statistic,
    latch_series,
)
from fdisim.detection.isolation import isolate
from fdisim.detection.residuals import ResidualComputer, stream_tag

CUSUM_CAP = 1.5  # saturación del CUSUM, en múltiplos de su límite h
INFORMATIVE_ONLY: tuple[str, ...] = ("P-101:1",)  # residuos que se muestran pero no deciden


def split_normal_data(normal_data: Any) -> tuple[Any, Any]:
    """Acepta ``{"train": df, "val": df}``, ``(train, val)`` o un único DataFrame."""
    if isinstance(normal_data, Mapping):
        return normal_data["train"], normal_data.get("val", normal_data["train"])
    if isinstance(normal_data, tuple | list):
        return normal_data[0], normal_data[1]
    return normal_data, normal_data


def iter_runs(data: Any) -> list[Any]:
    if "run_id" not in data.columns:
        return [data.sort_values("sim_time")]
    return [frame.sort_values("sim_time") for _, frame in data.groupby("run_id", sort=False)]


def decision_settings(config: Mapping[str, Any] | None) -> dict[str, Any]:
    detection = dict((config or {}).get("detection", {}))
    decision = dict(detection.get("decision", {}))
    residuals = dict(detection.get("residuals", {}))
    horizons = residuals.get("multistep_horizons", residuals.get("multistep_horizon", [20, 120]))
    if isinstance(horizons, int | float):
        horizons = [int(horizons)]
    return {
        "horizons": [int(h) for h in horizons],
        "period_s": float(detection.get("period_s", 0.5)),
        "target_fpr": float(decision.get("target_fpr", 0.01)),
        "cusum_k": float(decision.get("cusum", {}).get("k", 0.5)),
        "ewma_lambda": float(decision.get("ewma", {}).get("lambda", 0.2)),
        "hold_s": float(decision.get("alarm_hold_s", 2.0)),
    }


def _ratio(statistic: float, limit: float) -> float:
    if limit > 0:
        return statistic / limit
    return math.inf if statistic > limit else 0.0


@register_detector(DetectorKind.CAUSAL)
class CausalDetector(Detector):
    def __init__(
        self,
        model_dir: str | Path | None = None,
        config: Mapping[str, Any] | None = None,
        *,
        scm: Any = None,
        calibration: Mapping[str, Any] | None = None,
    ) -> None:
        if scm is None:
            if model_dir is None:
                raise ValueError("Indique el modelo causal (model_dir o scm)")
            from fdisim.causal.model_store import load_model

            scm, _, _ = load_model(Path(model_dir))
        self.model_dir = model_dir
        self.config = dict(config or {})
        self.scm = scm
        self.settings = decision_settings(config)
        self.stats: dict[str, tuple[float, float]] = {}
        self.limits: dict[str, dict[str, float]] = {}
        self.info: dict[str, Any] = {}
        if calibration is not None:
            self._load_calibration(calibration)
        self._build()

    # ------------------------------------------------------------------ estado
    def _build(self) -> None:
        s = self.settings
        self.residuals = ResidualComputer(self.scm, s["horizons"], self.stats)
        self.streams = self.residuals.names
        self.decision_streams = tuple(n for n in self.streams if n not in INFORMATIVE_ONLY)
        self.warmup = max(s["horizons"])
        # CUSUM y EWMA solo sobre los residuos a un paso: los del gemelo ya integran la
        # historia (están muy autocorrelacionados) y basta un umbral.
        self.accumulated = tuple(n for n in self.decision_streams if n.endswith(":1"))
        self.cusums = {}
        for name in self.accumulated:
            h = self.limits.get(name, {}).get("cusum", math.inf)
            self.cusums[name] = Cusum(s["cusum_k"], h, cap=CUSUM_CAP * h)
        self.ewmas = {name: Ewma(s["ewma_lambda"], 1.0) for name in self.accumulated}
        self.latch = AlarmLatch(s["hold_s"])
        self.tracker = AlarmTracker(DetectorKind.CAUSAL, "C")
        self._alarm_tags: dict[str, float] = {}
        self._samples = 0

    def reset(self) -> None:
        self._samples = 0
        self.residuals.reset()
        for rule in (*self.cusums.values(), *self.ewmas.values()):
            rule.reset()
        self.latch.reset()
        self.tracker.reset()
        self._alarm_tags = {}

    @property
    def calibrated(self) -> bool:
        return bool(self.limits)

    # ------------------------------------------------------------------ calibración
    def residual_frame(self, data: Any) -> Any:
        """Residuos crudos de todas las filas (el cálculo se reinicia en cada corrida)."""
        import pandas as pd

        computer = ResidualComputer(self.scm, self.settings["horizons"])
        frames = []
        for run in iter_runs(data):
            computer.reset()
            rows = [computer.update(values) for values in run.to_dict("records")]
            frames.append(pd.DataFrame(rows, index=run.index, columns=list(computer.names)))
        return pd.concat(frames)

    def fit(self, normal_data: Any) -> CausalDetector:
        """Estadísticas de los residuos (entrenamiento) y límites de decisión (validación)."""
        s = self.settings
        train, val = split_normal_data(normal_data)
        raw = self.residual_frame(train)
        self.stats = {
            name: (float(np.nanmean(raw[name])), float(np.nanstd(raw[name], ddof=1)))
            for name in self.streams
        }
        self.residuals.stats = dict(self.stats)

        # Estadísticos de cada regla en validación, por corrida (los acumuladores no cruzan
        # fronteras entre corridas).
        per_run: list[dict[str, dict[str, np.ndarray]]] = []
        raw_val = self.residual_frame(val)
        for run in iter_runs(val):
            block = raw_val.loc[run.index]
            stats_run: dict[str, dict[str, np.ndarray]] = {}
            for name in self.decision_streams:
                mean, std = self.stats[name]
                z = ((block[name] - mean) / std).to_numpy(float)
                stats_run[name] = {"z": z}
                if name in self.accumulated:
                    stats_run[name]["cusum"] = cusum_statistic(z, s["cusum_k"])
                    stats_run[name]["ewma"] = ewma_statistic(z, s["ewma_lambda"])
            per_run.append(stats_run)
        pooled = {
            name: {key: np.concatenate([r[name][key] for r in per_run]) for key in per_run[0][name]}
            for name in self.decision_streams
        }
        hold = max(1, int(round(s["hold_s"] / s["period_s"])))
        warmup = self.warmup

        def limits_for(eps: float) -> dict[str, dict[str, float]]:
            out = {}
            for name, series in pooled.items():
                z = series["z"][np.isfinite(series["z"])]
                out[name] = {
                    "upper": float(np.quantile(z, 1.0 - eps / 2, method="higher")),
                    "lower": float(np.quantile(z, eps / 2, method="lower")),
                }
                for key in ("cusum", "ewma"):
                    if key in series:
                        out[name][key] = float(np.quantile(series[key], 1.0 - eps, method="higher"))
            return out

        def alarm_rate(eps: float) -> float:
            limits = limits_for(eps)
            alarms = []
            for run in per_run:
                raw_alarm = np.zeros(len(next(iter(run.values()))["z"]), dtype=bool)
                for name, series in run.items():
                    lim = limits[name]
                    z = np.nan_to_num(series["z"], nan=0.0)
                    raw_alarm |= (z > lim["upper"]) | (z < lim["lower"])
                    for key in ("cusum", "ewma"):
                        if key in series:
                            raw_alarm |= series[key] > lim[key]
                raw_alarm[: warmup + 1] = False  # arranque sin alarmas
                alarms.append(latch_series(raw_alarm, hold))
            return float(np.mean(np.concatenate(alarms)))

        eps, val_fpr = calibrate_limits(alarm_rate, s["target_fpr"])
        self.limits = limits_for(eps)
        self.info = {
            "epsilon_per_rule": eps,
            "val_fpr": val_fpr,
            "train_rows": int(len(train)),
            "val_rows": int(len(val)),
        }
        self._build()
        return self

    # ------------------------------------------------------------------ detección
    def _stream_ratios(self, name: str, value: float) -> list[tuple[float, AlarmKind]]:
        """Cociente estadístico / límite de cada regla del residuo (> 1: la regla dispara)."""
        lim = self.limits[name]
        ratios: list[tuple[float, AlarmKind]] = []
        if math.isfinite(value):
            ratio = max(_ratio(value, lim["upper"]), _ratio(-value, -lim["lower"]), 0.0)
            if value > lim["upper"] or value < lim["lower"]:
                ratio = max(ratio, 1.0 + 1e-9)
            else:
                ratio = min(ratio, 1.0)
            ratios.append((ratio, AlarmKind.RESIDUAL))
        if name in self.cusums:
            cusum, ewma = self.cusums[name], self.ewmas[name]
            cusum.update(value)
            ewma.update(value)
            ratios.append((_ratio(cusum.statistic, lim["cusum"]), AlarmKind.CUSUM))
            ratios.append((_ratio(abs(ewma.value), lim["ewma"]), AlarmKind.EWMA))
        return ratios

    def update(self, t: float, values: Mapping[str, float]) -> DetectionResult:
        if not self.calibrated:
            raise RuntimeError("El detector causal no está calibrado (fit o calibración)")
        start = time.perf_counter()
        z = self.residuals.normalize(self.residuals.update(values))
        self._samples += 1
        armed = self._samples > self.warmup + 1
        scores: dict[str, float] = {}
        triggered: list[str] = []
        best: tuple[float, AlarmKind] = (0.0, AlarmKind.RESIDUAL)
        tag_scores: dict[str, float] = {}
        severity = 0.0  # mayor cociente estadístico / límite (puntuación continua, ROC)
        for name in self.streams:
            value = z[name]
            scores[name] = value
            if name not in self.limits:
                continue  # residuo informativo
            ratios = self._stream_ratios(name, value)
            if name in self.cusums:
                scores[f"cusum:{name}"] = self.cusums[name].statistic
                scores[f"ewma:{name}"] = self.ewmas[name].value
            if not ratios:
                continue
            severity = max(severity, *(r for r, _ in ratios))
            fired = [item for item in ratios if item[0] > 1.0] if armed else []
            if fired:
                triggered.append(name)
                top = max(fired, key=lambda item: item[0])
                tag = stream_tag(name)
                tag_scores[tag] = max(tag_scores.get(tag, 0.0), top[0])
                if top[0] > best[0]:
                    best = top

        scores["max"] = severity
        latched = self.latch.update(t, bool(triggered))
        if latched:
            for tag, score in tag_scores.items():
                self._alarm_tags[tag] = max(self._alarm_tags.get(tag, 0.0), score)
        suspected = isolate(self._alarm_tags, self._alarm_tags) if latched else None
        alarms = self.tracker.update(
            t, latched, kind=best[1], variables=tag_scores, score=best[0], suspected=suspected
        )
        if not latched:
            self._alarm_tags = {}
        return DetectionResult(
            t=t,
            scores=scores,
            alarms=alarms,
            suspected_tag=suspected,
            processing_time_s=time.perf_counter() - start,
            alarm=latched,
            triggered=tuple(triggered),
        )

    # ------------------------------------------------------------------ persistencia
    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "streams": list(self.streams),
            "stats": {k: list(v) for k, v in self.stats.items()},
            "limits": self.limits,
            "info": self.info,
        }

    def _load_calibration(self, data: Mapping[str, Any]) -> None:
        self.settings = {**self.settings, **dict(data.get("settings", {}))}
        self.stats = {k: (float(v[0]), float(v[1])) for k, v in data["stats"].items()}
        self.limits = {k: dict(v) for k, v in data["limits"].items()}
        self.info = dict(data.get("info", {}))
