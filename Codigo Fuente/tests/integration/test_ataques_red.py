"""Integración de la Fase 4: inyección FDI en el gateway comprometido con SignAndEncrypt.

Cubre RF-16 (valores falsos válidos en el protocolo y gateway transparente fuera de la
ventana), RF-17 (sesgo recibido = b), RF-21 (eventos de ataque por el plano de experimento),
RF-23 (ataque armado en caliente) y RF-24 (orden del actuador alterada y oculta).
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

pytest.importorskip("asyncua")

from fdisim.attacks.injector import FdiInjector  # noqa: E402
from fdisim.attacks.scheduler import AttackScheduler  # noqa: E402
from fdisim.common.bus import EventType, ExperimentHub  # noqa: E402
from fdisim.common.clock import CoSimClock  # noqa: E402
from fdisim.common.config import load_config  # noqa: E402
from fdisim.common.types import (  # noqa: E402
    LT_102,
    P_101,
    AttackSpec,
    AttackType,
    StealthSpec,
)
from fdisim.opcua.client_base import OpcUaClient  # noqa: E402
from fdisim.opcua.factory import endpoint_url, free_port  # noqa: E402
from fdisim.opcua.gateway import AggregatingGateway  # noqa: E402
from fdisim.opcua.plant_server import PlantServer  # noqa: E402
from fdisim.opcua.security import SecurityConfig, setup_pki  # noqa: E402
from fdisim.process.plant import Plant  # noqa: E402

pytestmark = pytest.mark.integration
SCALE = 4.0
STEALTH = StealthSpec(enabled=True, envelope=(2.0, 45.0), max_rate_per_s=0.5)


@pytest.fixture(scope="module")
def security(tmp_path_factory):
    certs = tmp_path_factory.mktemp("pki")
    setup_pki(certs)
    return SecurityConfig(certs_dir=certs)


async def _chain(security: SecurityConfig, attacks: list[AttackSpec]):
    cfg = load_config().to_dict()
    hub = ExperimentHub(["plant_server", "gateway"], multiprocess=False)
    plant_ep = endpoint_url("127.0.0.1", free_port(), "/planta")
    gateway_ep = endpoint_url("127.0.0.1", free_port(), "/gateway")
    plant = PlantServer(
        plant_ep,
        Plant.from_config(cfg["plant"], 0.1, seed=9),
        CoSimClock(0.1, SCALE),
        security,
        hub.bus_for("plant_server"),
    )
    await plant.start()
    injector = FdiInjector(AttackScheduler(attacks), hub.bus_for("gateway"))
    gateway = AggregatingGateway(
        gateway_ep,
        OpcUaClient(plant_ep, security, "gateway", "plant_server"),
        injector,
        security,
        hub.bus_for("gateway"),
        publishing_interval_ms=20,
        time_scale=SCALE,
    )
    await gateway.start()
    stop = asyncio.Event()
    relay = asyncio.create_task(gateway.relay_forever(stop))
    return hub, plant, gateway, stop, relay


async def _close(plant, gateway, stop, relay, *clients):
    for client in clients:
        await client.disconnect()
    stop.set()
    await relay
    await gateway.stop()
    await plant.stop()


def test_sesgo_inyectado_en_el_gateway_cifrado(security):
    async def scenario():
        attack = AttackSpec("A1", AttackType.BIAS, (LT_102,), 5.0, 10.0, {"bias": 2.0}, STEALTH)
        hub, plant, gateway, stop, relay = await _chain(security, [attack])
        monitor = OpcUaClient(gateway.endpoint, security, "monitor", "gateway")
        await monitor.connect()
        received = []
        await monitor.subscribe([LT_102], received.append, 100, every_update=True)
        await plant.run(20.0)
        await asyncio.sleep(0.6)
        await _close(plant, gateway, stop, relay, monitor)

        events = hub.drain(0.1)
        truth = {
            round(e.payload.source_ts, 4): e.payload
            for e in events
            if e.type is EventType.GROUND_TRUTH
        }
        attack_events = [e.payload for e in events if e.type is EventType.ATTACK]
        assert [(e.attack_id, e.t_end) for e in attack_events] == [("A1", None), ("A1", 15.0)]
        diffs = []
        for s in received:
            record = truth.get(round(s.source_ts, 4))
            if record is not None:
                diffs.append((record.sim_time, s.value - record.measured_values[LT_102], s.status))
        t, d, status = (np.array(x) for x in zip(*diffs, strict=True))
        assert len(t) >= 199 and set(status) == {"Good"}  # RF-16: válido en el protocolo
        assert np.all(np.abs(d[(t < 5.0) | (t >= 15.0)]) < 1e-9)  # transparente fuera
        assert d[(t >= 9.5) & (t < 10.5)] == pytest.approx(2.0)  # RF-17

    asyncio.run(scenario())


def test_actuador_alterado_y_oculto_y_ataque_en_caliente(security):
    async def scenario():
        attack = AttackSpec("A1", AttackType.BIAS, (P_101,), 2.0, 30.0, {"bias": 8.0})
        hub, plant, gateway, stop, relay = await _chain(security, [attack])
        controller = OpcUaClient(gateway.endpoint, security, "controller", "gateway")
        await controller.connect()
        run = asyncio.create_task(plant.run(40.0))
        await asyncio.sleep(1.5)  # t ≈ 6 s: dentro de la ventana
        await controller.write(P_101, 50.0)
        await asyncio.sleep(0.5)
        assert plant._read(P_101) == pytest.approx(58.0)  # noqa: SLF001  la planta recibe 58
        assert (await controller.read(P_101)).value == pytest.approx(50.0)  # el cliente ve 50

        # RF-23: replay armado en caliente sobre LT-102, con grabación del historial
        replay = AttackSpec("HMI-1", AttackType.REPLAY, (LT_102,), 0.0, 5.0, {"record_s": 3.0})
        gateway.arm_attack(replay, start_now=True)
        await run
        await asyncio.sleep(0.3)
        await _close(plant, gateway, stop, relay, controller)
        armed = [
            e.payload
            for e in hub.drain(0.1)
            if e.type is EventType.ATTACK and e.payload.attack_id == "HMI-1"
        ]
        assert armed and armed[0].t_start > 5.0
        assert armed[-1].t_end == pytest.approx(armed[0].t_start + 5.0)

    asyncio.run(scenario())
