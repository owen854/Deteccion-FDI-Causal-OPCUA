"""Criterios de aceptación de RF-01 (modelo de dos tanques)."""

from __future__ import annotations

import pytest

from conftest import pending
from fdisim.process.two_tank_model import TankParams, TwoTankModel, TwoTankParams

PARAMS = TwoTankParams(
    tank1=TankParams(area_cm2=153.9, outlet_area_cm2=0.50, max_height_cm=50.0),
    tank2=TankParams(area_cm2=153.9, outlet_area_cm2=0.40, max_height_cm=50.0),
)


@pending("Fase 2", "RF-01")
def test_estado_estacionario_analitico():
    h1, h2 = TwoTankModel(PARAMS).steady_state(q_in=88.6)
    assert h1 == pytest.approx((88.6 / 0.50) ** 2 / (2 * 981.0), rel=1e-9)
    assert h2 == pytest.approx((88.6 / 0.40) ** 2 / (2 * 981.0), rel=1e-9)


@pending("Fase 2", "RF-01")
def test_simulacion_converge_al_estado_estacionario():
    model = TwoTankModel(PARAMS)
    expected = model.steady_state(q_in=88.6)
    h = (5.0, 5.0)
    for _ in range(int(3600 / 0.1)):  # 1 h simulada
        h = model.step(h, q_in=88.6, dt=0.1)
    assert h[0] == pytest.approx(expected[0], rel=0.01)
    assert h[1] == pytest.approx(expected[1], rel=0.01)


@pending("Fase 2", "RF-01")
def test_niveles_saturados_en_rango_fisico():
    h = TwoTankModel(PARAMS).step((49.9, 49.9), q_in=1000.0, dt=10.0)
    assert 0.0 <= h[0] <= 50.0 and 0.0 <= h[1] <= 50.0
