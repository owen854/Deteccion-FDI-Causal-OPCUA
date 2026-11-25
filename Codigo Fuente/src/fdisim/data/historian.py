"""Historiador de series de tiempo (RF-25, RF-14).

Acumula en memoria las muestras OPC UA recibidas, la verdad de terreno, los eventos de ataque y
las salidas de los detectores, cada uno en su tabla (``samples``, ``ground_truth``,
``attacks``, ``detections`` y ``alarms``), y las vuelca a disco cada ``flush_every`` filas
para no perder datos si un proceso termina de forma abrupta.

- ``samples``: formato largo, una fila por muestra con las tres marcas de tiempo (fuente,
  servidor y recepción) y el StatusCode (RF-14).
- ``ground_truth``: una fila por paso de simulación; columnas ``true_<tag>`` (valor físico) y
  ``meas_<tag>`` (lo que publicó el sensor).

Formatos: Parquet (por defecto, escritura incremental) o CSV (RNF-13).

Implementado en la Fase 3 (muestras y verdad de terreno); ataques en la Fase 4 y detecciones y
alarmas en la Fase 6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fdisim.common.types import Alarm, AttackEvent, GroundTruthRecord, Sample

TABLES = ("samples", "ground_truth", "attacks", "detections", "alarms")
_STRING_COLUMNS = {
    "tag",
    "status",
    "attack_id",
    "type",
    "targets",
    "params",
    "detector",
    "suspected",
    "triggered",
    "scores",
    "alarm_id",
    "kind",
    "variables",
    "suspected_tag",
    "state",
}
_BOOL_COLUMNS = {"attack_active"}


def _arrow_type(column: str) -> Any:
    import pyarrow as pa

    if column in _STRING_COLUMNS:
        return pa.string()
    if column in _BOOL_COLUMNS:
        return pa.bool_()
    return pa.float64()


class Historian:
    def __init__(self, run_dir: Path, flush_every: int = 1000, fmt: str = "parquet") -> None:
        if fmt not in ("parquet", "csv"):
            raise ValueError(f"Formato no soportado: {fmt}")
        self.run_dir = Path(run_dir)
        self.flush_every = flush_every
        self.fmt = fmt
        self.counts: dict[str, int] = dict.fromkeys(TABLES, 0)
        self._rows: dict[str, list[dict[str, Any]]] = {t: [] for t in TABLES}
        self._writers: dict[str, Any] = {}
        self._closed = False

    def path_of(self, table: str) -> Path:
        return self.run_dir / f"{table}.{self.fmt}"

    def record_sample(self, sample: Sample) -> None:
        self._append(
            "samples",
            {
                "tag": sample.tag,
                "value": float(sample.value),
                "source_ts": sample.source_ts,
                "server_ts": sample.server_ts,
                "received_ts": sample.received_ts,
                "status": sample.status,
            },
        )

    def record_ground_truth(self, record: GroundTruthRecord) -> None:
        row: dict[str, Any] = {
            "sim_time": record.sim_time,
            "source_ts": record.source_ts if record.source_ts is not None else float("nan"),
        }
        row.update({f"true_{tag}": float(v) for tag, v in record.true_values.items()})
        row.update({f"meas_{tag}": float(v) for tag, v in record.measured_values.items()})
        row["attack_active"] = bool(record.attack_active)
        row["attack_id"] = record.attack_id
        self._append("ground_truth", row)

    def record_attack(self, event: AttackEvent) -> None:
        """Intervalo de ataque (tabla ``attacks``); se guarda tal como llega (inicio o fin)."""
        import json

        self._append(
            "attacks",
            {
                "attack_id": event.attack_id,
                "type": event.type.value,
                "targets": ",".join(event.targets),
                "t_start": float(event.t_start),
                "t_end": float(event.t_end) if event.t_end is not None else float("nan"),
                "params": json.dumps(dict(event.params), sort_keys=True),
            },
        )

    def record_detection(
        self,
        t: float,
        detector: str,
        scores: dict[str, float],
        *,
        alarm: bool = False,
        suspected: str | None = None,
        triggered: tuple[str, ...] = (),
        processing_ms: float | None = None,
    ) -> None:
        """Salida de un detector en un instante de la rejilla (puntuaciones en JSON)."""
        import json
        import math

        clean = {k: (round(v, 6) if math.isfinite(v) else None) for k, v in scores.items()}
        self._append(
            "detections",
            {
                "sim_time": float(t),
                "detector": detector,
                "alarm": float(alarm),
                "suspected": suspected or "",
                "triggered": ",".join(triggered),
                "processing_ms": float(processing_ms)
                if processing_ms is not None
                else float("nan"),
                "scores": json.dumps(clean, sort_keys=True),
            },
        )

    def record_alarm(self, alarm: Alarm) -> None:
        """Una fila al abrir la alarma (``active``) y otra al cerrarla (``closed``)."""
        self._append(
            "alarms",
            {
                "alarm_id": alarm.alarm_id,
                "detector": alarm.detector.value,
                "kind": alarm.kind.value,
                "t": float(alarm.t),
                "t_end": float(alarm.t_end) if alarm.t_end is not None else float("nan"),
                "variables": ",".join(alarm.variables),
                "score": float(alarm.score),
                "suspected_tag": alarm.suspected_tag or "",
                "state": alarm.state.value,
            },
        )

    def flush(self) -> None:
        for table in TABLES:
            self._flush_table(table)

    def close(self) -> None:
        """Vuelca lo pendiente y cierra los archivos; es seguro llamarla dos veces."""
        if self._closed:
            return
        self.flush()
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()
        self._closed = True

    # ------------------------------------------------------------------
    def _append(self, table: str, row: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("El historiador ya está cerrado")
        rows = self._rows[table]
        rows.append(row)
        self.counts[table] += 1
        if len(rows) >= self.flush_every:
            self._flush_table(table)

    def _flush_table(self, table: str) -> None:
        rows = self._rows[table]
        if not rows:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.fmt == "csv":
            import pandas as pd

            path = self.path_of(table)
            pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False)
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq

            writer = self._writers.get(table)
            if writer is None:
                schema = pa.schema([(c, _arrow_type(c)) for c in rows[0]])
                writer = pq.ParquetWriter(self.path_of(table), schema)
                self._writers[table] = writer
            columns = {name: [row.get(name) for row in rows] for name in writer.schema.names}
            writer.write_table(pa.Table.from_pydict(columns, schema=writer.schema))
        rows.clear()
