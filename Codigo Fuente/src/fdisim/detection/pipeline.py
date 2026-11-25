"""Calibración, carga y ejecución de los detectores sobre corridas y datasets (RF-34, RF-38).

- ``calibrate_detectors``: ajusta el detector causal (estadísticas de residuos en
  entrenamiento y límites en validación) y el método base (μ y σ en entrenamiento) y guarda
  ``detector.json`` junto al modelo causal.
- ``load_detectors``: carga ambos detectores calibrados; si falta la calibración, la hace con
  el dataset de origen del modelo (lo indica su manifiesto).
- ``run_detectors``: procesa una rejilla alineada (una o varias corridas) con los mismos objetos
  ``Detector`` que usa el monitor en línea, muestra a muestra (RF-38).
- ``evaluate``: métricas por corrida, escenario y detector (RF-41, RF-42, RF-37).
- ``detect_run`` y ``detect_dataset``: los usa ``fdisim detect`` y el modo offline.

Implementado en la Fase 6.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common import paths
from fdisim.common.types import PROCESS_TAGS, DetectorKind
from fdisim.detection.base import Detector
from fdisim.detection.causal_detector import CausalDetector, iter_runs
from fdisim.detection.threshold_detector import ThresholdDetector

DETECTOR_FILE = "detector.json"
GRACE_S = 10.0  # una alarma hasta 10 s después del fin del ataque aún cuenta como detección
# Tras un ataque, el gemelo de horizonte largo conserva anclas falsas durante H·Δt (60 s) y el
# lazo se recupera del daño físico; esos 120 s no se cuentan como operación normal en el FPR
# de las corridas atacadas. Las corridas normales se evalúan completas.
RECOVERY_S = 120.0
DETECTOR_LABELS = {DetectorKind.CAUSAL.value: "Causal", DetectorKind.THRESHOLD.value: "Base"}

Progress = Callable[[str], None] | None


def _say(progress: Progress, message: str) -> None:
    if progress is not None:
        progress(message)


def model_dir_of(config: Mapping[str, Any]) -> Path:
    return paths.resolve(
        config.get("detection", {}).get("causal_model_dir", "data/models/causal_v1")
    )


def model_available(config: Mapping[str, Any], model_dir: Path | None = None) -> bool:
    return ((model_dir or model_dir_of(config)) / "manifest.json").is_file()


# ---------------------------------------------------------------------- calibración y carga
def calibrate_detectors(
    model_dir: Path,
    config: Mapping[str, Any],
    train: Any,
    val: Any,
    *,
    dataset: Mapping[str, Any] | None = None,
    progress: Progress = None,
) -> Path:
    """Calibra ambos detectores y guarda ``detector.json`` junto al modelo."""
    from fdisim.data.storage import git_commit, sha256_file

    model_dir = Path(model_dir)
    _say(
        progress, "Calibrando el detector causal (residuos en entrenamiento, límites en validación)"
    )
    causal = CausalDetector(model_dir, config).fit((train, val))
    _say(progress, "Calibrando el método base de umbrales")
    base = ThresholdDetector.from_config(config).fit((train, val))
    base_val = run_detectors(val, [base])
    base.info = {"val_fpr": float(base_val.frames["threshold"]["alarm"].mean())}
    data = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "model_manifest_sha256": sha256_file(model_dir / "manifest.json"),
        "dataset": dict(dataset or {}),
        "causal": causal.to_dict(),
        "threshold": base.to_dict(),
    }
    path = model_dir / DETECTOR_FILE
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _say(
        progress,
        f"FPR en validación: causal {100 * causal.info['val_fpr']:.2f} % "
        f"(objetivo {100 * causal.settings['target_fpr']:.2f} %), "
        f"base {100 * base.info['val_fpr']:.2f} %",
    )
    return path


def calibrate_from_manifest(
    model_dir: Path, config: Mapping[str, Any], progress: Progress = None
) -> Path:
    """Calibra con los conjuntos de entrenamiento y validación con que se entrenó el modelo."""
    import pandas as pd

    manifest = json.loads((Path(model_dir) / "manifest.json").read_text(encoding="utf-8"))
    dataset = manifest.get("dataset", {})
    train_path = paths.resolve(dataset["train"])
    val_path = paths.resolve(dataset.get("val") or dataset["train"])
    train, val = pd.read_parquet(train_path), pd.read_parquet(val_path)
    return calibrate_detectors(
        model_dir,
        config,
        train,
        val,
        dataset={"train": str(dataset["train"]), "val": str(dataset.get("val"))},
        progress=progress,
    )


def load_detectors(
    config: Mapping[str, Any],
    model_dir: Path | None = None,
    *,
    calibrate: bool = True,
    progress: Progress = None,
) -> list[Detector]:
    """Detector causal y método base calibrados (en ese orden)."""
    model_dir = Path(model_dir or model_dir_of(config))
    path = model_dir / DETECTOR_FILE
    if not path.is_file():
        if not calibrate:
            raise FileNotFoundError(f"Los detectores no están calibrados: falta {path}")
        calibrate_from_manifest(model_dir, config, progress)
    data = json.loads(path.read_text(encoding="utf-8"))
    causal = CausalDetector(model_dir, config, calibration=data["causal"])
    return [causal, ThresholdDetector.from_dict(data["threshold"])]


# ---------------------------------------------------------------------- ejecución
@dataclass
class DetectionOutputs:
    frames: dict[str, Any]  # por detector: una fila por muestra
    alarms: Any  # una fila por alarma (ambos detectores)


def result_row(run_id: str, result: Any) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "sim_time": result.t,
        "alarm": int(result.alarm),
        "suspected": result.suspected_tag or "",
        "triggered": ",".join(result.triggered),
        "processing_ms": 1000.0 * (result.processing_time_s or 0.0),
        **result.scores,
    }


def alarm_row(run_id: str, alarm: Any) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "alarm_id": alarm.alarm_id,
        "detector": alarm.detector.value,
        "kind": alarm.kind.value,
        "t": alarm.t,
        "t_end": alarm.t_end if alarm.t_end is not None else float("nan"),
        "variables": ",".join(alarm.variables),
        "score": alarm.score,
        "suspected_tag": alarm.suspected_tag or "",
        "state": alarm.state.value,
    }


def run_detectors(
    grid: Any, detectors: Sequence[Detector], progress: Progress = None
) -> DetectionOutputs:
    """Procesa cada corrida de la rejilla con todos los detectores, muestra a muestra."""
    import pandas as pd

    rows: dict[str, list[dict[str, Any]]] = {d.kind.value: [] for d in detectors}
    alarms: list[dict[str, Any]] = []
    runs = iter_runs(grid)
    for i, run in enumerate(runs, 1):
        run_id = str(run["run_id"].iloc[0]) if "run_id" in run.columns else "run"
        for detector in detectors:
            detector.reset()
        for values in run[["sim_time", *PROCESS_TAGS]].to_dict("records"):
            t = float(values["sim_time"])
            for detector in detectors:
                rows[detector.kind.value].append(result_row(run_id, detector.update(t, values)))
        for detector in detectors:
            alarms.extend(alarm_row(run_id, a) for a in detector.tracker.history)  # type: ignore[attr-defined]
        if len(runs) > 1:
            _say(progress, f"Corrida {i}/{len(runs)} procesada ({run_id})")
    return DetectionOutputs(
        {kind: pd.DataFrame(items) for kind, items in rows.items()},
        pd.DataFrame(alarms, columns=ALARM_COLUMNS),
    )


ALARM_COLUMNS = (
    "run_id",
    "alarm_id",
    "detector",
    "kind",
    "t",
    "t_end",
    "variables",
    "score",
    "suspected_tag",
    "state",
)


# ---------------------------------------------------------------------- evaluación
def attack_windows(run: Any, period_s: float) -> list[dict[str, Any]]:
    """Ataques de una corrida etiquetada: id, inicio, fin y variables atacadas."""
    out = []
    if "attack_id" not in run.columns:
        return out
    ids = run["attack_id"].fillna("").astype(str)
    for attack_id in [a for a in dict.fromkeys(ids) if a]:
        part = run[ids == attack_id]
        targets = [
            tag
            for tag in PROCESS_TAGS
            if f"atk_{tag}" in part.columns and part[f"atk_{tag}"].max() > 0
        ]
        out.append(
            {
                "attack_id": attack_id,
                "t_start": float(part["sim_time"].min()),
                "t_end": float(part["sim_time"].max()) + period_s,
                "targets": targets,
            }
        )
    return out


def evaluate(grid: Any, outputs: DetectionOutputs, period_s: float = 0.5) -> Any:
    """Métricas por corrida y detector (una fila por corrida, detector y ataque o normal)."""
    import pandas as pd

    from fdisim.evaluation.metrics import (
        detection_delays,
        false_alarms_per_hour,
        false_positive_rate,
        precision_recall_f1,
        roc_auc,
    )

    rows = []
    for run in iter_runs(grid):
        run_id = str(run["run_id"].iloc[0]) if "run_id" in run.columns else "run"
        scenario = str(run["scenario"].iloc[0]) if "scenario" in run.columns else ""
        labels = (
            (run["label"].to_numpy() > 0).astype(int)
            if "label" in run.columns
            else np.zeros(len(run), int)
        )
        windows = attack_windows(run, period_s)
        for kind, frame in outputs.frames.items():
            part = frame[frame["run_id"] == run_id]
            alarm = part["alarm"].to_numpy(int)
            n = min(len(alarm), len(labels))
            alarm, y = alarm[:n], labels[:n]
            al = outputs.alarms
            onsets = al.loc[(al["run_id"] == run_id) & (al["detector"] == kind), "t"].to_numpy(
                float
            )
            precision, recall, f1 = precision_recall_f1(y, alarm)
            # La recuperación tras un ataque no cuenta como operación normal (ver RECOVERY_S).
            t_run = run["sim_time"].to_numpy(float)[:n]
            keep = np.ones(n, dtype=bool)
            for w in windows:
                keep &= ~((t_run >= w["t_end"]) & (t_run < w["t_end"] + RECOVERY_S))
            base = {
                "run_id": run_id,
                "scenario": scenario,
                "detector": kind,
                "fpr": false_positive_rate(y[keep], alarm[keep]),
                "false_alarms_per_h": false_alarms_per_hour(y[keep], alarm[keep], period_s),
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "auc": roc_auc(y, part["max"].to_numpy(float)[:n])
                if "max" in part
                else float("nan"),
                "processing_p95_ms": float(np.percentile(part["processing_ms"], 95))
                if len(part)
                else float("nan"),
            }
            if not windows:
                rows.append(
                    {
                        **base,
                        "attack_id": "",
                        "targets": "",
                        "detected": np.nan,
                        "delay_s": np.nan,
                        "identified": "",
                    }
                )
                continue
            delays = detection_delays(
                [(w["t_start"], w["t_end"]) for w in windows], onsets, GRACE_S
            )
            times = part["sim_time"].to_numpy(float)
            for window, delay in zip(windows, delays, strict=True):
                inside = (times >= window["t_start"]) & (times <= window["t_end"] + GRACE_S)
                votes = part.loc[inside & (part["alarm"].to_numpy() > 0), "suspected"]
                votes = votes[votes != ""]
                identified = votes.mode().iloc[0] if len(votes) else ""
                rows.append(
                    {
                        **base,
                        "attack_id": window["attack_id"],
                        "targets": ",".join(window["targets"]),
                        "detected": float(delay is not None),
                        "delay_s": delay if delay is not None else np.nan,
                        "identified": identified,
                        "identification_ok": float(identified in window["targets"])
                        if delay is not None
                        else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def summarize(metrics: Any) -> Any:
    """Resumen por escenario y detector (media de las corridas)."""
    if metrics.empty:
        return metrics
    agg = {
        "runs": ("run_id", "nunique"),
        "dr": ("detected", "mean"),
        "delay_mean_s": ("delay_s", "mean"),
        "delay_median_s": ("delay_s", "median"),
        "fpr": ("fpr", "mean"),
        "false_alarms_per_h": ("false_alarms_per_h", "mean"),
        "f1": ("f1", "mean"),
        "auc": ("auc", "mean"),
        "processing_p95_ms": ("processing_p95_ms", "max"),
    }
    if "identification_ok" in metrics.columns:
        agg["identification"] = ("identification_ok", "mean")
    return metrics.groupby(["scenario", "detector"], sort=True).agg(**agg).reset_index()


# ---------------------------------------------------------------------- comandos
def save_outputs(outputs: DetectionOutputs, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, frame in outputs.frames.items():
        frame.to_parquet(out_dir / f"{kind}.parquet", index=False)
    outputs.alarms.to_csv(out_dir / "alarms.csv", index=False)


def compare_online(
    run_dir: Path, outputs: DetectionOutputs, period_s: float
) -> dict[str, Any] | None:
    """Compara las alarmas del monitor en línea con las del reprocesamiento (RF-38)."""
    import pandas as pd

    path = next(
        (
            run_dir / f"alarms.{ext}"
            for ext in ("parquet", "csv")
            if (run_dir / f"alarms.{ext}").is_file()
        ),
        None,
    )
    if path is None:
        return None
    online = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    online = online[online["state"] == "active"]
    result: dict[str, Any] = {}
    for kind in outputs.frames:
        a = np.sort(online.loc[online["detector"] == kind, "t"].to_numpy(float))
        b = np.sort(outputs.alarms.loc[outputs.alarms["detector"] == kind, "t"].to_numpy(float))
        diffs = [float(np.min(np.abs(b - t))) if b.size else float("inf") for t in a]
        result[kind] = {
            "online": int(a.size),
            "offline": int(b.size),
            "max_diff_s": max(diffs) if diffs else 0.0,
            "match": bool(a.size == b.size and all(d <= period_s + 1e-9 for d in diffs)),
        }
    return result


def detect_run(
    run_dir: Path,
    config: Mapping[str, Any],
    model_dir: Path | None = None,
    progress: Progress = None,
) -> dict[str, Any]:
    """Reprocesa una corrida guardada y deja los resultados en ``<run_dir>/detection``."""
    from fdisim.data.dataset import run_table

    period_s = float(config.get("detection", {}).get("period_s", 0.5))
    detectors = load_detectors(config, model_dir, progress=progress)
    grid = run_table(Path(run_dir), period_s)
    outputs = run_detectors(grid, detectors)
    out_dir = Path(run_dir) / "detection"
    save_outputs(outputs, out_dir)
    metrics = evaluate(grid, outputs, period_s)
    metrics.to_csv(out_dir / "metrics.csv", index=False)
    summary = {
        "run_dir": str(run_dir),
        "rows": int(len(grid)),
        "metrics": json.loads(metrics.to_json(orient="records")),
        "online_vs_offline": compare_online(Path(run_dir), outputs, period_s),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return summary


def detect_dataset(
    data_path: Path,
    config: Mapping[str, Any],
    out_dir: Path,
    model_dir: Path | None = None,
    progress: Progress = None,
) -> dict[str, Any]:
    """Evalúa ambos detectores sobre un dataset etiquetado (p. ej., ``test.parquet``)."""
    import pandas as pd

    from fdisim.evaluation.detection_report import write_report

    period_s = float(config.get("detection", {}).get("period_s", 0.5))
    detectors = load_detectors(config, model_dir, progress=progress)
    grid = pd.read_parquet(data_path)
    _say(progress, f"Procesando {grid['run_id'].nunique()} corridas ({len(grid)} filas)")
    outputs = run_detectors(grid, detectors, progress)
    save_outputs(outputs, out_dir)
    metrics = evaluate(grid, outputs, period_s)
    summary = summarize(metrics)
    metrics.to_csv(out_dir / "metrics_by_run.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    calibration = json.loads(
        (Path(model_dir or model_dir_of(config)) / DETECTOR_FILE).read_text(encoding="utf-8")
    )
    report = write_report(out_dir, grid, outputs, metrics, summary, calibration, data_path)
    return report
