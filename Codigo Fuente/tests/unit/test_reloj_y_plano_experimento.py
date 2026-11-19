"""Reloj de co-simulación (RF-05), plano de experimento (RF-06, RF-54) y bitácora (RF-55)."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from fdisim.common.bus import (
    Command,
    CommandType,
    EventType,
    ExperimentBus,
    ExperimentHub,
)
from fdisim.common.clock import CoSimClock
from fdisim.common.logging_setup import configure_logging, log_path
from fdisim.common.types import GroundTruthRecord


def _collect(clock: CoSimClock, duration_s: float, body=None) -> list[float]:
    async def run() -> list[float]:
        out = []
        async for t in clock.ticks(duration_s):
            out.append(t)
            if body:
                body(t)
        return out

    return asyncio.run(run())


def test_reloj_genera_pasos_fijos_y_escala_el_tiempo():
    # A 4× cada paso dura 25 ms de pared, más que la resolución del temporizador de Windows
    # (≈ 15,6 ms cuando el sistema no concede 1 ms), así que no debe haber pasos atrasados.
    clock = CoSimClock(dt_s=0.1, time_scale=4.0)
    start = time.perf_counter()
    ticks = _collect(clock, 2.0)
    elapsed = time.perf_counter() - start
    assert len(ticks) == 20
    assert ticks[0] == pytest.approx(0.1) and ticks[-1] == pytest.approx(2.0)
    assert 0.48 <= elapsed < 1.2  # 2 s simulados a 4× ≈ 0,5 s de pared
    assert clock.stats.steps == 20 and clock.stats.overruns == 0
    # La deriva no se acumula (instantes absolutos); en 2 s la domina el atraso del último paso.
    # El criterio de RF-05 (< 1 % en 10 min) se verifica en las corridas largas.
    assert clock.stats.drift_pct < 5.0


def test_reloj_traduce_tiempo_simulado_a_epoca_y_viceversa():
    clock = CoSimClock(dt_s=0.1, time_scale=4.0)
    with pytest.raises(RuntimeError):
        clock.epoch_of(1.0)
    _collect(clock, 0.4)
    epoch = clock.epoch_of(8.0)
    assert epoch == pytest.approx(clock.start_epoch + 2.0)
    assert clock.sim_time_of(epoch) == pytest.approx(8.0)


def test_reloj_cuenta_pasos_atrasados():
    clock = CoSimClock(dt_s=0.01, time_scale=1.0)
    _collect(clock, 0.05, body=lambda t: time.sleep(0.03) if t < 0.015 else None)
    assert clock.stats.overruns >= 1
    assert clock.stats.max_lag_s >= 0.01


def test_reloj_rechaza_parametros_invalidos():
    with pytest.raises(ValueError):
        CoSimClock(dt_s=0.0)
    with pytest.raises(ValueError):
        CoSimClock(dt_s=0.1, time_scale=-1)


def test_plano_de_experimento_entrega_eventos_y_comandos():
    hub = ExperimentHub(["plant_server", "gateway"], multiprocess=False)
    plant = hub.bus_for("plant_server")
    record = GroundTruthRecord(0.1, {"LT-102": 25.0}, {"LT-102": 25.01}, source_ts=1.5)
    plant.publish_ground_truth(record)
    plant.publish(EventType.READY)
    events = hub.drain(0.1)
    assert [e.type for e in events] == [EventType.GROUND_TRUTH, EventType.READY]
    assert events[0].payload == record and events[0].source == "plant_server"

    hub.send_command("gateway", Command(CommandType.STOP))
    assert plant.poll_commands() == []
    assert hub.bus_for("gateway").poll_commands() == [Command(CommandType.STOP)]
    with pytest.raises(KeyError):
        plant.send_command("desconocido", Command(CommandType.START))


def test_bus_desconectado_ignora_publicaciones():
    bus = ExperimentBus("plant_server")
    assert not bus.connected
    bus.publish_ground_truth(GroundTruthRecord(0.1, {}, {}))
    assert bus.poll_commands() == []


def test_bitacora_por_componente_con_identificador_de_corrida(tmp_path):
    logger = configure_logging("gateway", "corrida-1", "INFO", tmp_path)
    logger.info("mensaje de prueba")
    configure_logging("gateway", "corrida-1", "INFO", tmp_path)  # idempotente
    logging.getLogger("fdisim.gateway").info("segundo")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = log_path("gateway", "corrida-1", tmp_path).read_text(encoding="utf-8")
    assert "| corrida-1 | fdisim.gateway | mensaje de prueba" in text
    assert text.count("segundo") == 1
    configure_logging("otro", "corrida-1", "INFO", tmp_path)  # libera el archivo anterior
