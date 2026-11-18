"""Criterios de aceptación de RF-07 (PID discreto)."""

from __future__ import annotations

import pytest

from fdisim.common.config import ConfigError
from fdisim.control.pid import PIDController, PIDParams


def test_accion_proporcional_pura():
    pid = PIDController(PIDParams(kp=2.0, ki=0.0, kd=0.0, ts_s=0.5))
    assert pid.update(setpoint=10.0, measurement=0.0) == pytest.approx(20.0)


def test_accion_integral_acumula_el_error():
    pid = PIDController(PIDParams(kp=0.0, ki=1.0, kd=0.0, ts_s=0.5))
    outputs = [pid.update(10.0, 8.0) for _ in range(3)]
    assert outputs == pytest.approx([1.0, 2.0, 3.0])


def test_salida_siempre_saturada():
    pid = PIDController(PIDParams(kp=50.0, ki=1.0, kd=0.0, ts_s=0.5, out_min=0.0, out_max=100.0))
    for _ in range(100):
        assert 0.0 <= pid.update(setpoint=1000.0, measurement=0.0) <= 100.0
    for _ in range(100):
        assert 0.0 <= pid.update(setpoint=-1000.0, measurement=0.0) <= 100.0


@pytest.mark.parametrize("anti_windup", ["clamping", "back_calculation"])
def test_anti_windup_permite_recuperacion_rapida(anti_windup):
    """Tras una saturación prolongada, la salida debe abandonar el límite al invertirse el error."""
    pid = PIDController(PIDParams(kp=1.0, ki=0.5, kd=0.0, ts_s=0.5, anti_windup=anti_windup))
    for _ in range(1000):
        pid.update(setpoint=100.0, measurement=0.0)
    assert pid.update(setpoint=0.0, measurement=10.0) < 100.0


def test_derivada_sobre_la_medicion_sin_pico_por_consigna():
    pid = PIDController(PIDParams(kp=1.0, ki=0.0, kd=20.0, ts_s=0.5, out_min=-1e6, out_max=1e6))
    pid.update(25.0, 25.0)
    assert pid.update(30.0, 25.0) == pytest.approx(5.0)  # solo acción P: la medición no cambió
    assert pid.update(30.0, 26.0) < 4.0  # la subida de la medición frena la acción


def test_arranque_sin_saltos():
    pid = PIDController(PIDParams(kp=2.5, ki=0.015, kd=0.0, ts_s=0.5))
    pid.reset(initial_output=59.0)
    assert pid.update(setpoint=25.0, measurement=25.0) == pytest.approx(59.0)


def test_parametros_invalidos():
    with pytest.raises(ConfigError):
        PIDParams(kp=-1.0, ki=0.0, kd=0.0, ts_s=0.5)
    with pytest.raises(ConfigError):
        PIDParams(kp=1.0, ki=0.0, kd=0.0, ts_s=0.0)
    with pytest.raises(ConfigError):
        PIDParams.from_config({"kp": 1.0, "ts_s": 0.5, "anti_windup": "ninguno"})
