"""Criterios de aceptación de RF-01 y RF-02 (modelo de dos tanques)."""

from __future__ import annotations

import pytest

from fdisim.common.config import ConfigError
from fdisim.process.two_tank_model import TankParams, TwoTankModel, TwoTankParams

PARAMS = TwoTankParams(
    tank1=TankParams(area_cm2=153.9, outlet_area_cm2=0.50, max_height_cm=50.0),
    tank2=TankParams(area_cm2=153.9, outlet_area_cm2=0.40, max_height_cm=50.0),
)


def test_estado_estacionario_analitico():
    h1, h2 = TwoTankModel(PARAMS).steady_state(q_in=88.6)
    assert h1 == pytest.approx((88.6 / 0.50) ** 2 / (2 * 981.0), rel=1e-9)
    assert h2 == pytest.approx((88.6 / 0.40) ** 2 / (2 * 981.0), rel=1e-9)


def test_derivadas_nulas_en_equilibrio():
    model = TwoTankModel(PARAMS)
    dh1, dh2 = model.derivatives(model.steady_state(88.6), 88.6)
    assert dh1 == pytest.approx(0.0, abs=1e-12) and dh2 == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("integrator", ["solve_ivp", "rk4"])
def test_simulacion_converge_al_estado_estacionario(integrator):
    model = TwoTankModel(PARAMS, integrator)
    expected = model.steady_state(q_in=88.6)
    h = (5.0, 5.0)
    for _ in range(3600):  # 1 h simulada con Δt = 1 s
        h = model.step(h, q_in=88.6, dt=1.0)
    assert h[0] == pytest.approx(expected[0], rel=0.01)
    assert h[1] == pytest.approx(expected[1], rel=0.01)


def test_integradores_coinciden():
    a, b = TwoTankModel(PARAMS, "solve_ivp"), TwoTankModel(PARAMS, "rk4")
    ha = hb = (10.0, 30.0)
    for _ in range(600):
        ha = a.step(ha, 120.0, 0.1)
        hb = b.step(hb, 120.0, 0.1)
    assert ha == pytest.approx(hb, abs=1e-4)


def test_niveles_saturados_en_rango_fisico():
    h = TwoTankModel(PARAMS).step((49.9, 49.9), q_in=1000.0, dt=10.0)
    assert 0.0 <= h[0] <= 50.0 and 0.0 <= h[1] <= 50.0
    empty = TwoTankModel(PARAMS, "rk4").step((0.01, 0.01), q_in=0.0, dt=60.0)
    assert empty == (pytest.approx(0.0, abs=0.05), pytest.approx(0.0, abs=0.05))


def test_perturbaciones_modifican_la_dinamica():
    model = TwoTankModel(PARAMS)
    h = model.steady_state(88.6)
    _, dh2 = model.derivatives(h, 88.6, {"tank2.outlet_scale": 1.1})
    dh1, _ = model.derivatives(h, 88.6, {"tank1.leak": 2.0})
    assert dh2 < 0 and dh1 == pytest.approx(-2.0 / 153.9)


@pytest.mark.parametrize(
    ("tank", "field"),
    [
        ({"area_cm2": -1, "outlet_area_cm2": 0.5, "max_height_cm": 50}, "plant.tank1.area_cm2"),
        (
            {"area_cm2": 150, "outlet_area_cm2": 200, "max_height_cm": 50},
            "plant.tank1.outlet_area_cm2",
        ),
        ({"area_cm2": 150, "outlet_area_cm2": 0.5}, "plant.tank1.max_height_cm"),
    ],
)
def test_parametros_invalidos_se_rechazan_indicando_el_campo(tank, field):
    ok = {"area_cm2": 150, "outlet_area_cm2": 0.4, "max_height_cm": 50}
    with pytest.raises(ConfigError, match=field.replace(".", r"\.")):
        TwoTankParams.from_config({"tank1": tank, "tank2": ok})


def test_integrador_desconocido():
    with pytest.raises(ConfigError):
        TwoTankModel(PARAMS, "euler")
