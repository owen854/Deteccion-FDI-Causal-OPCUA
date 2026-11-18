"""Verificación del cifrado OPC UA con Wireshark/tshark (RF-12, criterio «Wireshark muestra la
carga cifrada»).

Captura en la interfaz de loopback (Npcap) dos sesiones idénticas cliente → servidor
(navegación, lectura, escritura de la consigna y suscripción):

- ``SignAndEncrypt`` con la política configurada (identidad gateway → plant_server).
- ``None`` (solo para comparar; usuario anónimo para no exponer credenciales).

Luego busca en los bytes capturados textos que viajan dentro de los servicios OPC UA
(``PlantaDosTanques``, ``Consigna``, ``Tanque2``) y resume los mensajes con el disector OPC UA
de tshark. Con cifrado los textos no deben aparecer; sin cifrado, sí.

Uso::

    python scripts/verificar_cifrado.py [--politica Aes256_Sha256_RsaPss]

Las capturas quedan en ``results/fase1/`` (abrirlas con Wireshark para inspección visual).
Requiere Wireshark con Npcap y soporte de loopback.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fdisim.common import paths  # noqa: E402
from fdisim.opcua.factory import create_client, create_server, endpoint_url  # noqa: E402
from fdisim.opcua.information_model import NAMESPACE_URI, ROOT_OBJECT  # noqa: E402
from fdisim.opcua.security import SecurityConfig, SecurityMode, UserAuth  # noqa: E402

MARKERS = (b"PlantaDosTanques", b"Consigna", b"Tanque2")
LOOPBACK = r"\Device\NPF_Loopback"


def find_tshark() -> str:
    found = shutil.which("tshark") or r"C:\Program Files\Wireshark\tshark.exe"
    if not Path(found).is_file():
        raise SystemExit("No se encontró tshark. Instale Wireshark con Npcap.")
    return found


async def session(port: int, security: SecurityConfig) -> None:
    """Sesión representativa: navegar, leer, escribir la consigna y suscribirse 2 s."""
    from asyncua import ua

    endpoint = endpoint_url("127.0.0.1", port, "/fdisim/planta")
    server, nodes = await create_server(endpoint, security, "plant_server")
    async with server:
        client = await create_client(endpoint, security, "gateway", "plant_server")
        async with client:
            idx = await client.get_namespace_index(NAMESPACE_URI)
            root = await client.nodes.objects.get_child(f"{idx}:{ROOT_OBJECT}")
            for folder in await root.get_children():
                await folder.get_children()
            sp = client.get_node(ua.NodeId("Control.Consigna", idx))
            await sp.read_value()
            await sp.write_value(ua.DataValue(ua.Variant(27.5, ua.VariantType.Double)))
            sub = await client.create_subscription(100, None)
            await sub.subscribe_data_change(client.get_node(ua.NodeId("Tanque2.Nivel", idx)))
            for i in range(20):
                await nodes["LT-102"].write_value(25.0 + i * 0.01)
                await asyncio.sleep(0.1)
            await sub.delete()


def capture(tshark: str, port: int, security: SecurityConfig, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [
            tshark,
            "-i",
            LOOPBACK,
            "-f",
            f"tcp port {port}",
            "-a",
            "duration:12",
            "-q",
            "-w",
            str(out),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(3.0)  # tiempo para que tshark abra la interfaz
    asyncio.run(session(port, security))
    _, err = proc.communicate(timeout=30)
    if proc.returncode not in (0, None) or not out.is_file():
        raise SystemExit(f"tshark falló (¿permisos de Npcap?): {err.strip()}")


def analyze(tshark: str, port: int, pcap: Path) -> dict:
    raw = pcap.read_bytes()
    info = subprocess.run(
        [
            tshark,
            "-r",
            str(pcap),
            "-d",
            f"tcp.port=={port},opcua",
            "-Y",
            "opcua",
            "-T",
            "fields",
            "-e",
            "_ws.col.info",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.splitlines()
    kinds = collections.Counter(line.split(":")[0].strip() for line in info if line.strip())
    return {
        "captura": str(pcap),
        "bytes": len(raw),
        "mensajes_opcua": len(info),
        "tipos": dict(kinds.most_common(8)),
        "textos_en_claro": {m.decode(): m in raw for m in MARKERS},
        "ejemplo_info": info[:6],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica el cifrado OPC UA con tshark.")
    parser.add_argument("--politica", default="Basic256Sha256")
    parser.add_argument("--puerto", type=int, default=4870)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger("asyncua").setLevel(logging.CRITICAL)

    tshark = find_tshark()
    outdir = paths.RESULTS_DIR / "fase1"
    runs = {
        "SignAndEncrypt": SecurityConfig(SecurityMode.SIGN_AND_ENCRYPT, args.politica),
        "None": SecurityConfig(
            SecurityMode.NONE, args.politica, UserAuth.ANONYMOUS, allow_insecure_debug=True
        ),
    }
    report = {}
    for i, (name, security) in enumerate(runs.items()):
        port = args.puerto + i
        pcap = outdir / f"captura_{name}.pcapng"
        print(f"Capturando sesión {name} en el puerto {port}...")
        capture(tshark, port, security, pcap)
        report[name] = analyze(tshark, port, pcap)

    secure, plain = report["SignAndEncrypt"], report["None"]
    ok = (
        secure["mensajes_opcua"] > 0
        and not any(secure["textos_en_claro"].values())
        and all(plain["textos_en_claro"].values())
    )
    for name, r in report.items():
        print(
            f"\n{name}: {r['mensajes_opcua']} mensajes OPC UA · "
            f"textos en claro: {r['textos_en_claro']}"
        )
        for line in r["ejemplo_info"][:4]:
            print(f"    {line}")
    report["conclusion"] = (
        "Con SignAndEncrypt la carga útil viaja cifrada; sin seguridad es legible."
        if ok
        else "Resultado inesperado: revisar las capturas."
    )
    out = outdir / "verificacion_cifrado.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{report['conclusion']}\nReporte: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
