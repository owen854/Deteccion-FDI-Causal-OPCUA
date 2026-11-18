"""Métricas de detección (RF-41, RF-42; OE4).

Definiciones (Documento 01, RF-41):

- **Tasa de detección por evento (DR):** fracción de ataques con al menos una alarma dentro de
  ``[tₛ, tₑ + gracia]``.
- **Tasa de falsos positivos (FPR):** ``FP / (FP + TN)`` sobre muestras etiquetadas como normales.
- **Retardo de detección:** ``t_primera_alarma − tₛ`` para cada ataque detectado (``None`` si no).
- **Precisión, exhaustividad y F1** por muestra; **ROC/AUC** barriendo el umbral.

Las funciones aceptan secuencias simples para poder validarse con casos sintéticos.
Fase de implementación: Fase 8.
"""

from __future__ import annotations

from collections.abc import Sequence

Window = tuple[float, float]  # (inicio, fin) de un ataque


def detection_rate(
    attack_windows: Sequence[Window], alarm_times: Sequence[float], grace_s: float = 0.0
) -> float:
    raise NotImplementedError("Fase 8 — RF-41: tasa de detección")


def detection_delays(
    attack_windows: Sequence[Window], alarm_times: Sequence[float], grace_s: float = 0.0
) -> list[float | None]:
    raise NotImplementedError("Fase 8 — RF-42: retardo de detección")


def false_positive_rate(labels: Sequence[int], predictions: Sequence[int]) -> float:
    raise NotImplementedError("Fase 8 — RF-41: tasa de falsos positivos")


def false_alarms_per_hour(
    labels: Sequence[int], predictions: Sequence[int], period_s: float
) -> float:
    raise NotImplementedError("Fase 8 — RF-41: falsas alarmas por hora")


def precision_recall_f1(
    labels: Sequence[int], predictions: Sequence[int]
) -> tuple[float, float, float]:
    raise NotImplementedError("Fase 8 — RF-41: precisión, exhaustividad y F1")


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    raise NotImplementedError("Fase 8 — RF-41: área bajo la curva ROC")
