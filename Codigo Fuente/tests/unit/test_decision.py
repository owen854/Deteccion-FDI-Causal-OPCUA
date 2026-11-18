"""Criterios de aceptación de RF-34 (reglas de decisión)."""

from __future__ import annotations

from conftest import pending
from fdisim.detection.decision import AlarmLatch, Cusum, Ewma


@pending("Fase 6", "RF-34")
def test_cusum_no_alarma_en_operacion_normal():
    cusum = Cusum(k=0.5, h=5.0)
    assert not any(cusum.update(0.0) for _ in range(1000))


@pending("Fase 6", "RF-34")
def test_cusum_detecta_desplazamiento_persistente():
    cusum = Cusum(k=0.5, h=5.0)
    alarms = [cusum.update(2.0) for _ in range(6)]
    assert alarms.index(True) == 3  # S = 1.5, 3.0, 4.5, 6.0 > h


@pending("Fase 6", "RF-34")
def test_cusum_bilateral():
    cusum = Cusum(k=0.5, h=5.0)
    assert any(cusum.update(-2.0) for _ in range(6))


@pending("Fase 6", "RF-34")
def test_ewma_detecta_desplazamiento():
    ewma = Ewma(lam=0.2, L=3.0)
    assert not any(ewma.update(0.0) for _ in range(100))
    assert any(ewma.update(3.0) for _ in range(3))


@pending("Fase 6", "RF-34")
def test_retencion_de_alarma():
    latch = AlarmLatch(hold_s=2.0)
    assert latch.update(0.0, True)
    assert latch.update(1.0, False)  # se mantiene durante hold_s
    assert not latch.update(2.5, False)
