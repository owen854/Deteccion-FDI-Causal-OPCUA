"""Criterios de aceptación de RF-07 (PID discreto)."""

from __future__ import annotations

import pytest

from conftest import pending
from fdisim.control.pid import PIDController, PIDParams


@pending("Fase 2", "RF-07")
def test_accion_proporcional_pura():
    pid = PIDController(PIDParams(kp=2.0, ki=0.0, kd=0.0, ts_s=0.5))
    assert pid.update(setpoint=10.0, measurement=0.0) == pytest.approx(20.0)


@pending("Fase 2", "RF-07")
def test_salida_siempre_saturada():
    pid = PIDController(PIDParams(kp=50.0, ki=1.0, kd=0.0, ts_s=0.5, out_min=0.0, out_max=100.0))
    for _ in range(100):
        assert 0.0 <= pid.update(setpoint=1000.0, measurement=0.0) <= 100.0
    for _ in range(100):
        assert 0.0 <= pid.update(setpoint=-1000.0, measurement=0.0) <= 100.0


@pending("Fase 2", "RF-07")
def test_anti_windup_permite_recuperacion_rapida():
    """Tras una saturación prolongada, la salida debe abandonar el límite al invertirse el error."""
    pid = PIDController(PIDParams(kp=1.0, ki=0.5, kd=0.0, ts_s=0.5, anti_windup="clamping"))
    for _ in range(1000):
        pid.update(setpoint=100.0, measurement=0.0)
    assert pid.update(setpoint=0.0, measurement=10.0) < 100.0
