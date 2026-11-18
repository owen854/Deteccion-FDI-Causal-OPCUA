"""Criterios de aceptación de RF-17, RF-18 y RF-19 (ataques FDI)."""

from __future__ import annotations

import pytest

from conftest import pending
from fdisim.attacks import create_attack
from fdisim.common.types import LT_102, AttackSpec, AttackType


def spec(kind: AttackType, **params: float) -> AttackSpec:
    return AttackSpec("A1", kind, (LT_102,), start_s=10.0, duration_s=20.0, params=params)


@pending("Fase 4", "RF-17")
def test_sesgo_suma_constante():
    attack = create_attack(spec(AttackType.BIAS, bias=2.0))
    assert attack.falsify(LT_102, 25.0, 12.0) == pytest.approx(27.0)
    assert attack.falsify(LT_102, 20.0, 29.0) == pytest.approx(22.0)


@pending("Fase 4", "RF-18")
def test_rampa_crece_linealmente_y_se_limita():
    attack = create_attack(spec(AttackType.RAMP, slope_per_s=0.1, max_deviation=1.5))
    assert attack.falsify(LT_102, 25.0, 10.0) == pytest.approx(25.0)
    assert attack.falsify(LT_102, 25.0, 20.0) == pytest.approx(26.0)
    assert attack.falsify(LT_102, 25.0, 29.0) == pytest.approx(26.5)  # limitado a Δ_max


@pending("Fase 4", "RF-19")
def test_replay_reproduce_la_ventana_grabada_en_bucle():
    attack = create_attack(spec(AttackType.REPLAY, record_s=5.0))
    for t in range(10):  # y(t) = t, grabación de [5, 10)
        attack.observe(LT_102, float(t), float(t))
    assert attack.falsify(LT_102, 99.0, 10.0) == pytest.approx(5.0)
    assert attack.falsify(LT_102, 99.0, 11.0) == pytest.approx(6.0)
    assert attack.falsify(LT_102, 99.0, 15.0) == pytest.approx(5.0)  # vuelve a empezar
