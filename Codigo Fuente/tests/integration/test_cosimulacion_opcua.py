"""Integración de la Fase 3: planta → gateway → controlador y monitor en un mismo proceso.

Cubre RF-06 (verdad de terreno), RF-08 (lazo cerrado por OPC UA), RF-09 (consigna en ≤ 1 s),
RF-13 (gateway transparente), RF-14/RF-25 (muestras completas con marcas de tiempo) y RF-15 /
RNF-07 (reconexión ≤ 5 s tras reiniciar el gateway). Usa una PKI temporal y puertos libres.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("asyncua")

from fdisim.common.bus import EventType, ExperimentHub  # noqa: E402
from fdisim.common.clock import CoSimClock  # noqa: E402
from fdisim.common.config import load_config  # noqa: E402
from fdisim.common.types import LT_102, P_101, SP_102  # noqa: E402
from fdisim.control.controller_client import ControllerClient  # noqa: E402
from fdisim.control.pid import PIDController, PIDParams  # noqa: E402
from fdisim.data.historian import Historian  # noqa: E402
from fdisim.detection.online_monitor import OnlineMonitor  # noqa: E402
from fdisim.opcua.client_base import OpcUaClient  # noqa: E402
from fdisim.opcua.factory import endpoint_url, free_port  # noqa: E402
from fdisim.opcua.gateway import AggregatingGateway  # noqa: E402
from fdisim.opcua.plant_server import PlantServer  # noqa: E402
from fdisim.opcua.security import SecurityConfig, setup_pki  # noqa: E402
from fdisim.orchestration.run_summary import data_quality  # noqa: E402
from fdisim.process.plant import Plant  # noqa: E402

pytestmark = pytest.mark.integration
SCALE = 4.0


@pytest.fixture(scope="module")
def security(tmp_path_factory):
    certs = tmp_path_factory.mktemp("pki")
    setup_pki(certs)
    return SecurityConfig(certs_dir=certs)


class Chain:
    """Planta + gateway transparente en el bucle de eventos actual."""

    def __init__(self, security: SecurityConfig) -> None:
        cfg = load_config().to_dict()
        self.cfg = cfg
        self.security = security
        self.hub = ExperimentHub(["plant_server", "gateway"], multiprocess=False)
        self.plant_ep = endpoint_url("127.0.0.1", free_port(), "/planta")
        self.gateway_ep = endpoint_url("127.0.0.1", free_port(), "/gateway")
        plant = Plant.from_config(cfg["plant"], 0.1, seed=5)
        self.plant = PlantServer(
            self.plant_ep, plant, CoSimClock(0.1, SCALE), security, self.hub.bus_for("plant_server")
        )
        self.gateway: AggregatingGateway | None = None
        self.gw_stop = asyncio.Event()
        self.gw_task: asyncio.Task | None = None

    async def start_gateway(self) -> None:
        upstream = OpcUaClient(self.plant_ep, self.security, "gateway", "plant_server")
        self.gateway = AggregatingGateway(
            self.gateway_ep, upstream, None, self.security, self.hub.bus_for("gateway")
        )
        await self.gateway.start()
        self.gw_stop = asyncio.Event()
        self.gw_task = asyncio.create_task(self.gateway.relay_forever(self.gw_stop))

    async def stop_gateway(self) -> None:
        self.gw_stop.set()
        await self.gw_task
        await self.gateway.stop()

    def ground_truth(self) -> pd.DataFrame:
        rows = []
        for event in self.hub.drain(0.1):
            if event.type is EventType.GROUND_TRUTH:
                r = event.payload
                rows.append(
                    {
                        "sim_time": r.sim_time,
                        "source_ts": r.source_ts,
                        **{f"meas_{k}": v for k, v in r.measured_values.items()},
                        **{f"true_{k}": v for k, v in r.true_values.items()},
                    }
                )
        return pd.DataFrame(rows)


def test_lazo_cerrado_y_gateway_transparente(security, tmp_path):
    async def scenario() -> None:
        chain = Chain(security)
        await chain.plant.start()
        await chain.start_gateway()
        historian = Historian(tmp_path, flush_every=100)
        monitor = OnlineMonitor(
            OpcUaClient(chain.gateway_ep, security, "monitor", "gateway"), [], historian, 0.5
        )
        await monitor.start()
        mon_task = asyncio.create_task(monitor.run())
        pid = PIDController(PIDParams.from_config(chain.cfg["control"]))
        controller = ControllerClient(
            chain.gateway_ep, pid, LT_102, P_101, security=security, time_scale=SCALE
        )
        await controller.start()
        ctl_task = asyncio.create_task(controller.run())
        hmi = OpcUaClient(chain.gateway_ep, security, "hmi", "gateway")
        await hmi.connect()

        run = asyncio.create_task(chain.plant.run(60.0))  # 60 s simulados ≈ 15 s de pared
        await asyncio.sleep(3.0)
        # RF-09: la consigna escrita en el gateway llega a la planta en ≤ 1 s de pared
        t0 = time.perf_counter()
        await hmi.write(SP_102, 27.0)
        while chain.plant._read(SP_102) != 27.0:  # noqa: SLF001
            assert time.perf_counter() - t0 < 1.0, "la consigna no llegó a la planta en 1 s"
            await asyncio.sleep(0.01)
        await run
        await asyncio.sleep(1.0)

        await controller.stop()
        await ctl_task
        await monitor.stop()
        await mon_task
        await hmi.disconnect()
        gw_stats = chain.gateway.stats()
        await chain.stop_gateway()
        await chain.plant.stop()

        gt = chain.ground_truth()
        assert len(gt) == 600  # RF-06: verdad de terreno del 100 % de los pasos
        samples = pd.read_parquet(tmp_path / "samples.parquet")
        quality = data_quality(samples, gt)
        for tag, item in quality["completeness"].items():
            assert item["pct"] >= 99.9, tag  # RF-25
            assert quality["transparency"][tag]["mismatches"] == 0, tag  # RF-13
        assert quality["latency_ms"]["end_to_end"]["n"] > 0
        assert gw_stats["forwarded_writes"] >= controller.updates  # escrituras del PID → planta
        assert controller.updates > 50 and controller.failed_writes == 0
        # RF-08: el PID reacciona al cambio de consigna a través de OPC UA
        assert (gt["true_P-101"].iloc[-1] - gt["true_P-101"].iloc[0]) > 1.0
        assert np.all(gt["true_LIC-102.SP"].iloc[-10:] == 27.0)

    asyncio.run(scenario())


def test_reconexion_tras_reiniciar_el_gateway(security):
    async def scenario() -> None:
        chain = Chain(security)
        await chain.plant.start()
        await chain.start_gateway()
        received: list[float] = []
        client = OpcUaClient(
            chain.gateway_ep, security, "monitor", "gateway", initial_delay_s=0.5, max_delay_s=5.0
        )
        await client.connect()
        await client.subscribe(
            ["LT-102"], lambda s: received.append(time.perf_counter()), 100, every_update=True
        )
        stop = asyncio.Event()
        watchdog = asyncio.create_task(client.run_with_reconnect(stop))
        plant_stop = asyncio.Event()
        run = asyncio.create_task(chain.plant.run(120.0, plant_stop))
        await asyncio.sleep(1.5)
        assert received, "sin datos antes de la caída"

        await chain.stop_gateway()
        await asyncio.sleep(1.0)
        restarted = time.perf_counter()
        await chain.start_gateway()
        while not [t for t in received if t > restarted]:
            assert time.perf_counter() - restarted < 5.0, "no se reconectó en 5 s (RNF-07)"
            await asyncio.sleep(0.05)
        recovery = min(t for t in received if t > restarted) - restarted
        assert client.reconnections >= 1
        assert recovery <= 5.0

        stop.set()
        await watchdog
        await client.disconnect()
        plant_stop.set()
        await run
        await chain.stop_gateway()
        await chain.plant.stop()

    asyncio.run(scenario())
