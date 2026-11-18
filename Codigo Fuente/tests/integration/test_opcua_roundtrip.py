"""Integración OPC UA: lectura, escritura y suscripción de ida y vuelta (RF-10, RF-11, RF-12).

Requiere asyncua; se omite si no está instalado.
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import pending

pytestmark = pytest.mark.integration


@pending("Fase 3", "RF-10/RF-11/RF-12")
def test_ida_y_vuelta_con_signandencrypt():
    pytest.importorskip("asyncua")
    from fdisim.opcua.client_base import OpcUaClient
    from fdisim.opcua.security import SecurityConfig

    async def scenario() -> None:
        client = OpcUaClient("opc.tcp://127.0.0.1:4840/fdisim/planta", SecurityConfig(), "test")
        await client.connect()
        tags = await client.browse_tags()
        assert "LT-102" in tags
        await client.write("LIC-102.SP", 30.0)
        assert (await client.read("LIC-102.SP")).value == pytest.approx(30.0)
        await client.disconnect()

    asyncio.run(scenario())
