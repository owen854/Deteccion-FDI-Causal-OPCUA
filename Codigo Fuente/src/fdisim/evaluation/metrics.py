"""Métricas de detección (RF-41, RF-42; OE4).

Definiciones (Documento 01, RF-41):

- **Tasa de detección por evento (DR):** fracción de ataques con al menos una alarma dentro de
  ``[tₛ, tₑ + gracia]``.
- **Tasa de falsos positivos (FPR):** ``FP / (FP + TN)`` sobre muestras etiquetadas como normales.
- **Retardo de detección:** ``t_primera_alarma − tₛ`` para cada ataque detectado (``None`` si no).
- **Precisión, exhaustividad y F1** por muestra; **ROC/AUC** barriendo el umbral.

Las funciones aceptan secuencias simples para poder validarse con casos sintéticos.
Implementado en la Fase 6 (adelantado de la Fase 8: lo necesita la evaluación del detector).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

Window = tuple[float, float]  # (inicio, fin) de un ataque


def detection_delays(
    attack_windows: Sequence[Window], alarm_times: Sequence[float], grace_s: float = 0.0
) -> list[float | None]:
    times = np.sort(np.asarray(alarm_times, dtype=float))
    delays: list[float | None] = []
    for start, end in attack_windows:
        inside = times[(times >= start) & (times <= end + grace_s)]
        delays.append(float(inside[0] - start) if inside.size else None)
    return delays


def detection_rate(
    attack_windows: Sequence[Window], alarm_times: Sequence[float], grace_s: float = 0.0
) -> float:
    if not attack_windows:
        return float("nan")
    delays = detection_delays(attack_windows, alarm_times, grace_s)
    return sum(d is not None for d in delays) / len(delays)


def _confusion(labels: Sequence[int], predictions: Sequence[int]) -> tuple[int, int, int, int]:
    y = np.asarray(labels, dtype=int) > 0
    p = np.asarray(predictions, dtype=int) > 0
    tp = int(np.sum(y & p))
    fp = int(np.sum(~y & p))
    tn = int(np.sum(~y & ~p))
    fn = int(np.sum(y & ~p))
    return tp, fp, tn, fn


def false_positive_rate(labels: Sequence[int], predictions: Sequence[int]) -> float:
    _, fp, tn, _ = _confusion(labels, predictions)
    return fp / (fp + tn) if fp + tn else float("nan")


def false_alarms_per_hour(
    labels: Sequence[int], predictions: Sequence[int], period_s: float
) -> float:
    """Alarmas (flancos de subida) que empiezan en muestras normales, por hora normal."""
    y = np.asarray(labels, dtype=int) > 0
    p = np.asarray(predictions, dtype=int) > 0
    rising = p & ~np.concatenate(([False], p[:-1]))
    normal_hours = np.sum(~y) * period_s / 3600.0
    return float(np.sum(rising & ~y) / normal_hours) if normal_hours > 0 else float("nan")


def precision_recall_f1(
    labels: Sequence[int], predictions: Sequence[int]
) -> tuple[float, float, float]:
    tp, fp, _, fn = _confusion(labels, predictions)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Área bajo la curva ROC (estadístico de Mann-Whitney, empates a la mitad)."""
    from scipy.stats import rankdata

    y = np.asarray(labels, dtype=int) > 0
    s = np.asarray(scores, dtype=float)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(s)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))
