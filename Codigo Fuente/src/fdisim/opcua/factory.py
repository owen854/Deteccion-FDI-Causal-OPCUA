"""Fábricas de servidores y clientes asyncua con la seguridad del proyecto (RF-11, RF-12).

Las usan la prueba de concepto de la Fase 1 y, desde la Fase 3, el servidor de planta, el
gateway, el controlador y el monitor, para que todos los enlaces compartan la misma
configuración de seguridad.
"""

from __future__ import annotations

import socket
from typing import Any

from fdisim.opcua.information_model import NAMESPACE_URI, build_address_space
from fdisim.opcua.security import (
    SecurityConfig,
    application_uri,
    apply_client_security,
    apply_server_security,
)


def endpoint_url(host: str, port: int, path: str = "/fdisim") -> str:
    return f"opc.tcp://{host}:{port}{path}"


def free_port(host: str = "127.0.0.1") -> int:
    """Puerto TCP libre en ``host`` (útil para pruebas en paralelo)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


async def create_server(
    endpoint: str, security: SecurityConfig, component: str, with_plant_model: bool = True
) -> tuple[Any, dict[str, Any]]:
    """Crea (sin iniciar) un servidor asyncua seguro y, opcionalmente, el modelo de la planta.

    Devuelve ``(servidor, {tag: nodo})``. El llamador ejecuta ``async with servidor:``.
    """
    from asyncua import Server

    server = Server()
    await server.init()
    server.set_endpoint(endpoint)
    server.set_server_name(f"FDISim-OPCUA {component}")
    await server.set_application_uri(application_uri(component))
    await apply_server_security(server, security, component)
    nodes: dict[str, Any] = {}
    if with_plant_model:
        idx = await server.register_namespace(NAMESPACE_URI)
        nodes = await build_address_space(server, idx)
    return server, nodes


async def create_client(
    endpoint: str,
    security: SecurityConfig,
    component: str,
    server_component: str,
    timeout_s: float = 4.0,
) -> Any:
    """Crea (sin conectar) un cliente asyncua seguro.

    El llamador ejecuta ``async with cliente:``.
    """
    from asyncua import Client

    client = Client(endpoint, timeout=timeout_s)
    await apply_client_security(client, security, component, server_component)
    return client
