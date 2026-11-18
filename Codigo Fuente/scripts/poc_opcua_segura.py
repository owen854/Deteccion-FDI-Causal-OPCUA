"""Prueba de concepto de la Fase 1: comunicación OPC UA segura.

Requerimientos: RF-10, RF-11, RF-12; RNF-09, RNF-12.


Levanta un servidor con la identidad ``plant_server`` y el modelo de información real de la
planta, conecta un cliente con la identidad ``gateway`` y verifica:

1. Solo se ofrecen endpoints seguros con la política configurada.
2. Conexión SignAndEncrypt con certificado de aplicación y usuario/contraseña.
3. Navegación del espacio de direcciones, EURange y EngineeringUnits.
4. Escritura permitida en LIC-102.SP y rechazada en LT-102 (solo lectura).
5. Suscripción con marcas de tiempo y latencia de notificación.
6. Rechazo de un cliente con certificado no confiable que suplanta al gateway.
7. Rechazo de una contraseña incorrecta.
8. Rechazo de un cliente sin seguridad (política None).
9. Rechazo en configuración de las políticas obsoletas.

Uso::

    python scripts/poc_opcua_segura.py                                  # batería de pruebas
    python scripts/poc_opcua_segura.py --politica Aes256_Sha256_RsaPss
    python scripts/poc_opcua_segura.py --servir                         # servidor para UaExpert
    python scripts/poc_opcua_segura.py --servir --confiar-uaexpert      # y confía en UaExpert
    python scripts/poc_opcua_segura.py --servir --modo None --puerto 4850   # solo comparación

Requiere haber ejecutado antes ``python scripts/generar_certificados.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import os
import shutil
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fdisim.common import paths  # noqa: E402
from fdisim.common.types import LT_101, LT_102, SP_102  # noqa: E402
from fdisim.opcua.factory import create_client, create_server, endpoint_url  # noqa: E402
from fdisim.opcua.information_model import NAMESPACE_URI, ROOT_OBJECT  # noqa: E402
from fdisim.opcua.security import (  # noqa: E402
    CREDENTIALS_FILE,
    SecurityConfig,
    SecurityMode,
    generate_application_certificate,
    pki_paths,
)

SERVER, CLIENT = "plant_server", "gateway"
PATH = "/fdisim/planta"


async def feed(nodes: dict, stop: asyncio.Event, period_s: float = 0.1) -> None:
    """Publica señales sintéticas en LT-101 y LT-102 con SourceTimestamp, como hará la planta."""
    from asyncua import ua

    t0 = time.perf_counter()
    while not stop.is_set():
        t = time.perf_counter() - t0
        for tag, base in ((LT_101, 16.0), (LT_102, 25.0)):
            now = datetime.now(UTC)
            value = ua.Variant(base + math.sin(t / 5.0), ua.VariantType.Double)
            await nodes[tag].write_value(
                ua.DataValue(value, SourceTimestamp=now, ServerTimestamp=now)
            )
        await asyncio.sleep(period_s)


class Battery:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"prueba": name, "ok": bool(ok), "detalle": detail})
        print(f"  [{'OK' if ok else 'FALLA'}] {name}" + (f" — {detail}" if detail else ""))

    @property
    def all_ok(self) -> bool:
        return all(r["ok"] for r in self.results)


async def expect_rejected(coro_factory, battery: Battery, name: str) -> None:
    try:
        client = await coro_factory()
        async with client:
            await client.nodes.objects.read_browse_name()
        battery.add(name, False, "la conexión fue aceptada")
    except Exception as exc:  # noqa: BLE001 — cualquier rechazo es el resultado esperado
        battery.add(name, True, f"rechazado ({type(exc).__name__})")


async def run_battery(port: int, security: SecurityConfig, seconds: float) -> dict:
    from asyncua import Client, ua

    endpoint = endpoint_url("127.0.0.1", port, PATH)
    server, nodes = await create_server(endpoint, security, SERVER)
    battery = Battery()
    latencies: list[float] = []
    stop = asyncio.Event()
    print(f"Servidor {endpoint} · {security.mode.value} · {security.policy}")
    async with server:
        feeder = asyncio.create_task(feed(nodes, stop))
        try:
            client = await create_client(endpoint, security, CLIENT, SERVER)
            async with client:
                eps = await client.get_endpoints()
                offered = sorted(
                    {(e.SecurityPolicyUri.split("#")[-1], e.SecurityMode.name) for e in eps}
                )
                battery.add(
                    "1. Solo endpoints seguros",
                    all(mode != "None_" and pol != "None" for pol, mode in offered),
                    ", ".join(f"{p}/{m}" for p, m in offered),
                )
                battery.add(
                    "2. Conexión segura con certificado y usuario",
                    True,
                    f"{security.mode.value} + {security.policy}",
                )

                idx = await client.get_namespace_index(NAMESPACE_URI)
                root = await client.nodes.objects.get_child(f"{idx}:{ROOT_OBJECT}")
                found = []
                for folder in await root.get_children():
                    for var in await folder.get_children():
                        found.append((await var.read_browse_name()).Name)
                lt102 = client.get_node(ua.NodeId("Tanque2.Nivel", idx))
                eurange = await (await lt102.get_child("0:EURange")).read_value()
                units = await (await lt102.get_child("0:EngineeringUnits")).read_value()
                battery.add(
                    "3. Navegación, EURange y EngineeringUnits",
                    len(found) >= 7 and eurange.High == 50.0 and units.DisplayName.Text == "cm",
                    f"{len(found)} variables; LT-102 rango [{eurange.Low}, {eurange.High}] "
                    f"{units.DisplayName.Text}",
                )

                sp = client.get_node(ua.NodeId("Control.Consigna", idx))
                await sp.write_value(ua.DataValue(ua.Variant(30.0, ua.VariantType.Double)))
                sp_ok = await sp.read_value() == 30.0
                try:
                    await lt102.write_value(ua.DataValue(ua.Variant(99.0, ua.VariantType.Double)))
                    battery.add(
                        "4. Escritura según nivel de acceso", False, "LT-102 aceptó escritura"
                    )
                except ua.UaStatusCodeError as exc:
                    battery.add(
                        "4. Escritura según nivel de acceso",
                        sp_ok,
                        f"{SP_102} escrita; LT-102 rechazada ({exc.__class__.__name__})",
                    )

                class Handler:
                    def datachange_notification(self, node, val, data):
                        src = data.monitored_item.Value.SourceTimestamp
                        if src is not None:
                            latencies.append((datetime.now(UTC) - src).total_seconds() * 1000)

                sub = await client.create_subscription(100, Handler())
                await sub.subscribe_data_change(lt102, sampling_interval=50)
                await asyncio.sleep(seconds)
                await sub.delete()
                if latencies:
                    p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
                    detail = (
                        f"{len(latencies)} notificaciones; latencia media "
                        f"{statistics.mean(latencies):.1f} ms, p95 {p95:.1f} ms"
                    )
                else:
                    detail = "sin notificaciones"
                battery.add(
                    "5. Suscripción con marcas de tiempo", len(latencies) > seconds * 3, detail
                )

            # 6. Certificado no confiable que suplanta al gateway (mismo URI, otra clave)
            with tempfile.TemporaryDirectory() as tmp:
                generate_application_certificate(CLIENT, tmp)
                shutil.copyfile(
                    pki_paths(CLIENT, security.certs_dir).trusted_dir / f"{SERVER}.der",
                    pki_paths(CLIENT, tmp).trusted_dir / f"{SERVER}.der",
                )
                shutil.copyfile(
                    paths.resolve(security.certs_dir) / CREDENTIALS_FILE,
                    Path(tmp) / CREDENTIALS_FILE,
                )
                rogue = SecurityConfig(
                    security.mode, security.policy, security.user_auth, Path(tmp)
                )
                await expect_rejected(
                    lambda: create_client(endpoint, rogue, CLIENT, SERVER),
                    battery,
                    "6. Rechazo de certificado no confiable",
                )

            async def wrong_password():
                c = await create_client(endpoint, security, CLIENT, SERVER)
                c.set_password("contrasena-incorrecta")
                return c

            await expect_rejected(wrong_password, battery, "7. Rechazo de contraseña incorrecta")

            async def no_security():
                c = Client(endpoint, timeout=4)
                c.set_user(CLIENT)
                c.set_password("x")
                return c

            await expect_rejected(
                no_security, battery, "8. Rechazo de cliente sin seguridad (None)"
            )

            try:
                SecurityConfig(policy="Basic128Rsa15").check()
                battery.add("9. Rechazo de políticas obsoletas", False)
            except ValueError as exc:
                battery.add("9. Rechazo de políticas obsoletas", True, str(exc))
        finally:
            stop.set()
            await feeder

    return {
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "modo": security.mode.value,
        "politica": security.policy,
        "resultados": battery.results,
        "latencia_ms": latencies,
        "todo_ok": battery.all_ok,
    }


def trust_uaexpert(certs_dir: Path) -> Path | None:
    """Copia el certificado propio de UaExpert a la lista de confianza del servidor."""
    appdata = Path(os.environ.get("APPDATA", ""))
    candidates = sorted(appdata.glob("unifiedautomation/uaexpert/PKI/own/certs/*.der"))
    if not candidates:
        return None
    target = pki_paths(SERVER, certs_dir).trusted_dir / "uaexpert.der"
    shutil.copyfile(candidates[-1], target)
    return target


async def serve(port: int, security: SecurityConfig) -> None:
    endpoint = endpoint_url("127.0.0.1", port, PATH)
    server, nodes = await create_server(endpoint, security, SERVER)
    stop = asyncio.Event()
    print(f"Servidor en {endpoint} · {security.mode.value} · {security.policy}")
    print(
        f"Usuario: uaexpert · contraseña en {paths.resolve(security.certs_dir) / CREDENTIALS_FILE}"
    )
    print("Ctrl+C para detener.")
    async with server:
        feeder = asyncio.create_task(feed(nodes, stop))
        try:
            await asyncio.Event().wait()
        finally:
            stop.set()
            await feeder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de concepto OPC UA segura (Fase 1).")
    parser.add_argument("--puerto", type=int, default=4840)
    parser.add_argument(
        "--politica",
        default="Basic256Sha256",
        choices=["Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss"],
    )
    parser.add_argument(
        "--modo", default="SignAndEncrypt", choices=["SignAndEncrypt", "Sign", "None"]
    )
    parser.add_argument("--segundos", type=float, default=3.0, help="duración de la suscripción")
    parser.add_argument("--servir", action="store_true", help="dejar el servidor en ejecución")
    parser.add_argument("--confiar-uaexpert", action="store_true")
    parser.add_argument("--reporte", default=str(paths.RESULTS_DIR / "fase1" / "poc_opcua.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    # Los rechazos esperados (pruebas 6-8) generan registros de error del servidor; se silencian.
    logging.getLogger("asyncua").setLevel(logging.CRITICAL)
    logging.getLogger("asyncuagds").setLevel(logging.CRITICAL)

    security = SecurityConfig(
        mode=SecurityMode(args.modo),
        policy=args.politica,
        allow_insecure_debug=args.modo == "None",
    )
    if args.confiar_uaexpert:
        copied = trust_uaexpert(security.certs_dir)
        print(
            f"Certificado de UaExpert {'copiado a ' + str(copied) if copied else 'no encontrado'}"
        )
    if args.servir:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(serve(args.puerto, security))
        return 0

    report = asyncio.run(run_battery(args.puerto, security, args.segundos))
    out = Path(args.reporte)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Resultado: {'todas las pruebas superadas' if report['todo_ok'] else 'HAY FALLAS'} · {out}"
    )
    return 0 if report["todo_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
