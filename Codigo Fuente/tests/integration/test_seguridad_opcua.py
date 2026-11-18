"""Integración de la Fase 1: seguridad OPC UA y modelo de información (RF-10, RF-11, RF-12; RNF-09).

Cada prueba crea una PKI temporal y levanta un servidor real en localhost con un puerto libre.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

asyncua = pytest.importorskip("asyncua")

from asyncua import Client, ua  # noqa: E402

from fdisim.opcua.factory import create_client, create_server, endpoint_url, free_port  # noqa: E402
from fdisim.opcua.information_model import NAMESPACE_URI, ROOT_OBJECT  # noqa: E402
from fdisim.opcua.security import (  # noqa: E402
    CREDENTIALS_FILE,
    SecurityConfig,
    build_trust_lists,
    create_credentials,
    generate_application_certificate,
    pki_paths,
)

pytestmark = pytest.mark.integration
TRUST = {"plant_server": ("gateway",), "gateway": ("plant_server",)}


@pytest.fixture
def security(tmp_path):
    for component in ("plant_server", "gateway"):
        generate_application_certificate(component, tmp_path)
    build_trust_lists(tmp_path, TRUST)
    create_credentials(tmp_path, users=("gateway",))
    return SecurityConfig(certs_dir=tmp_path)


def test_conexion_segura_modelo_y_niveles_de_acceso(security):
    async def scenario():
        endpoint = endpoint_url("127.0.0.1", free_port(), "/fdisim/planta")
        server, _ = await create_server(endpoint, security, "plant_server")
        async with server:
            client = await create_client(endpoint, security, "gateway", "plant_server")
            async with client:
                endpoints = await client.get_endpoints()
                assert {e.SecurityMode for e in endpoints} == {
                    ua.MessageSecurityMode.SignAndEncrypt
                }
                idx = await client.get_namespace_index(NAMESPACE_URI)
                root = await client.nodes.objects.get_child(f"{idx}:{ROOT_OBJECT}")
                names = [
                    (await v.read_browse_name()).Name
                    for f in await root.get_children()
                    for v in await f.get_children()
                ]
                assert len(names) == 7  # 5 variables de proceso + 2 de estado
                lt102 = client.get_node(ua.NodeId("Tanque2.Nivel", idx))
                assert (await (await lt102.get_child("0:EURange")).read_value()).High == 50.0
                units = await (await lt102.get_child("0:EngineeringUnits")).read_value()
                assert units.DisplayName.Text == "cm"
                sp = client.get_node(ua.NodeId("Control.Consigna", idx))
                await sp.write_value(ua.DataValue(ua.Variant(30.0, ua.VariantType.Double)))
                assert await sp.read_value() == 30.0
                with pytest.raises(ua.UaStatusCodeError):
                    await lt102.write_value(ua.DataValue(ua.Variant(1.0, ua.VariantType.Double)))

    asyncio.run(scenario())


def test_rechazos_de_seguridad(security, tmp_path_factory):
    rogue_dir = tmp_path_factory.mktemp("intruso")
    generate_application_certificate("gateway", rogue_dir)  # suplanta el URI del gateway
    shutil.copyfile(
        pki_paths("gateway", security.certs_dir).trusted_dir / "plant_server.der",
        pki_paths("gateway", rogue_dir).trusted_dir / "plant_server.der",
    )
    shutil.copyfile(security.certs_dir / CREDENTIALS_FILE, rogue_dir / CREDENTIALS_FILE)
    rogue = SecurityConfig(certs_dir=rogue_dir)

    async def rejected(make_client) -> bool:
        try:
            client = await make_client()
            async with client:
                await client.nodes.objects.read_browse_name()
        except Exception:  # noqa: BLE001
            return True
        return False

    async def scenario():
        endpoint = endpoint_url("127.0.0.1", free_port(), "/fdisim/planta")
        server, _ = await create_server(endpoint, security, "plant_server")
        async with server:
            assert await rejected(lambda: create_client(endpoint, rogue, "gateway", "plant_server"))

            async def wrong_password():
                c = await create_client(endpoint, security, "gateway", "plant_server")
                c.set_password("incorrecta")
                return c

            assert await rejected(wrong_password)

            async def no_security():
                return Client(endpoint, timeout=3)

            assert await rejected(no_security)

    asyncio.run(scenario())
