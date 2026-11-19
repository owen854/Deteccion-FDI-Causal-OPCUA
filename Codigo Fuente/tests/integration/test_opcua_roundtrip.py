"""Integración OPC UA: lectura, escritura y suscripción de ida y vuelta (RF-10 a RF-12, RF-14).

Levanta el servidor de planta con una PKI temporal y lo usa con el cliente genérico.
Requiere asyncua; se omite si no está instalado.
"""

from __future__ import annotations

import asyncio
import math

import pytest

pytest.importorskip("asyncua")

from fdisim.common.bus import ExperimentBus  # noqa: E402
from fdisim.common.clock import CoSimClock  # noqa: E402
from fdisim.common.config import load_config  # noqa: E402
from fdisim.opcua.client_base import OpcUaClient  # noqa: E402
from fdisim.opcua.factory import endpoint_url, free_port  # noqa: E402
from fdisim.opcua.plant_server import PlantServer  # noqa: E402
from fdisim.opcua.security import SecurityConfig, setup_pki  # noqa: E402
from fdisim.process.plant import Plant  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def security(tmp_path_factory):
    certs = tmp_path_factory.mktemp("pki")
    setup_pki(certs)
    return SecurityConfig(certs_dir=certs)


def test_ida_y_vuelta_con_signandencrypt(security):
    async def scenario() -> None:
        cfg = load_config().to_dict()
        endpoint = endpoint_url("127.0.0.1", free_port(), "/fdisim/planta")
        plant = Plant.from_config(cfg["plant"], 0.1, seed=3)
        server = PlantServer(
            endpoint, plant, CoSimClock(0.1, 2.0), security, ExperimentBus("plant_server")
        )
        await server.start()
        client = OpcUaClient(endpoint, security, "gateway", "plant_server")
        try:
            await client.connect()
            tags = await client.browse_tags()
            assert {"LT-101", "LT-102", "FT-101", "P-101", "LIC-102.SP"} <= set(tags)

            await client.write("LIC-102.SP", 30.0)
            assert (await client.read("LIC-102.SP")).value == pytest.approx(30.0)

            received = []
            await client.subscribe(["LT-102"], received.append, 50, every_update=True)
            await server.run(1.0)  # 10 pasos a 2×
            await asyncio.sleep(0.4)
            steps = [s for s in received if s.source_ts >= server.clock.start_epoch]
            assert len(steps) == 10  # una notificación por paso (StatusValueTimestamp)
            sample = steps[-1]
            assert sample.status == "Good"
            assert all(math.isfinite(x) for x in (sample.source_ts, sample.server_ts))
            assert sample.received_ts >= sample.server_ts >= sample.source_ts - 0.05
            assert sample.source_ts == pytest.approx(server.clock.epoch_of(1.0), abs=1e-6)
        finally:
            await client.disconnect()
            await server.stop()

    asyncio.run(scenario())
