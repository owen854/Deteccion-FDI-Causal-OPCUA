"""Etiquetas de ataque por muestra a partir de los intervalos ejecutados (RF-21).

Las etiquetas se derivan de los ``AttackEvent`` (tiempo simulado), no de los datos, de modo que
coinciden con la programación del escenario o con la orden interactiva:

- ``label``: 1 si algún ataque está activo en el instante de la muestra (RF-21);
- ``attack_id``: el ataque activo (el primero si hay varios);
- ``tag_attacked``: 1 si la variable de esa muestra es objetivo de un ataque activo (sirve para
  evaluar la identificación de la variable atacada, RF-37).

Implementado en la Fase 4.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from fdisim.common.types import AttackEvent, AttackType

EVENT_COLUMNS = ("attack_id", "type", "targets", "t_start", "t_end", "params")


def events_frame(events: Iterable[AttackEvent]) -> Any:
    """Tabla ``attacks`` del historiador: un intervalo por fila."""
    import pandas as pd

    rows = [
        {
            "attack_id": e.attack_id,
            "type": e.type.value,
            "targets": ",".join(e.targets),
            "t_start": float(e.t_start),
            "t_end": float(e.t_end) if e.t_end is not None else math.nan,
            "params": json.dumps(dict(e.params), sort_keys=True),
        }
        for e in events
    ]
    return pd.DataFrame(rows, columns=list(EVENT_COLUMNS))


def events_from_frame(frame: Any) -> list[AttackEvent]:
    out = []
    for row in frame.itertuples(index=False):
        end = (
            None
            if row.t_end is None or (isinstance(row.t_end, float) and math.isnan(row.t_end))
            else float(row.t_end)
        )
        out.append(
            AttackEvent(
                str(row.attack_id),
                AttackType(row.type),
                tuple(str(row.targets).split(",")),
                float(row.t_start),
                end,
                json.loads(row.params) if row.params else {},
            )
        )
    return out


def merge_events(events: Iterable[AttackEvent]) -> list[AttackEvent]:
    """Une los eventos de inicio y de fin de cada ataque (el último reporte gana)."""
    merged: dict[str, AttackEvent] = {}
    for event in events:
        current = merged.get(event.attack_id)
        if current is None or event.t_end is not None:
            merged[event.attack_id] = event
    return list(merged.values())


def _intervals(
    events: Iterable[AttackEvent], horizon: float
) -> list[tuple[str, tuple[str, ...], float, float]]:
    return [
        (
            e.attack_id,
            tuple(e.targets),
            float(e.t_start),
            float(e.t_end) if e.t_end is not None else horizon,
        )
        for e in events
    ]


def label_times(
    times: Any, events: Iterable[AttackEvent], tags: Any = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Etiquetas para instantes ``times`` (y, opcionalmente, la variable de cada muestra)."""
    t = np.asarray(times, dtype=float)
    label = np.zeros(t.size, dtype=np.int8)
    attacked = np.zeros(t.size, dtype=np.int8)
    attack_id = np.full(t.size, None, dtype=object)
    tag_arr = None if tags is None else np.asarray(tags, dtype=object)
    for aid, targets, start, end in _intervals(events, math.inf):
        inside = (t >= start) & (t < end)
        attack_id[inside & (label == 0)] = aid
        label[inside] = 1
        if tag_arr is not None:
            attacked[inside & np.isin(tag_arr, targets)] = 1
    return label, attack_id, attacked


def label_samples(samples: Any, events: Iterable[AttackEvent]) -> Any:
    """Agrega ``label``, ``attack_id`` y ``tag_attacked`` a una tabla con ``sim_time``."""
    label, attack_id, attacked = label_times(samples["sim_time"], list(events), samples["tag"])
    return samples.assign(label=label, attack_id=attack_id, tag_attacked=attacked)


def label_ground_truth(ground_truth: Any, events: Iterable[AttackEvent]) -> Any:
    label, attack_id, _ = label_times(ground_truth["sim_time"], list(events))
    return ground_truth.assign(attack_active=label.astype(bool), attack_id=attack_id)
