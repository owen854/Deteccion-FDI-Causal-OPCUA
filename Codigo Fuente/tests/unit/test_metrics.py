"""Criterios de aceptación de RF-41 y RF-42: métricas validadas con casos sintéticos."""

from __future__ import annotations

import pytest

from fdisim.evaluation.metrics import (
    detection_delays,
    detection_rate,
    false_positive_rate,
    precision_recall_f1,
    roc_auc,
)

WINDOWS = [(100.0, 200.0), (300.0, 400.0)]


def test_tasa_de_deteccion_por_evento():
    assert detection_rate(WINDOWS, [150.0]) == pytest.approx(0.5)
    assert detection_rate(WINDOWS, [150.0, 310.0]) == pytest.approx(1.0)
    assert detection_rate(WINDOWS, [50.0, 250.0]) == pytest.approx(0.0)


def test_retardo_de_deteccion():
    assert detection_delays(WINDOWS, [120.0, 130.0, 350.0]) == [
        pytest.approx(20.0),
        pytest.approx(50.0),
    ]
    assert detection_delays(WINDOWS, [120.0]) == [pytest.approx(20.0), None]


def test_tasa_de_falsos_positivos():
    labels = [0, 0, 0, 0, 1, 1]
    preds = [0, 1, 0, 0, 1, 0]
    assert false_positive_rate(labels, preds) == pytest.approx(0.25)


def test_precision_exhaustividad_f1():
    p, r, f1 = precision_recall_f1([0, 1, 1, 1], [1, 1, 1, 0])
    assert (p, r) == (pytest.approx(2 / 3), pytest.approx(2 / 3))
    assert f1 == pytest.approx(2 / 3)


def test_auc_perfecto_y_aleatorio():
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.5)
