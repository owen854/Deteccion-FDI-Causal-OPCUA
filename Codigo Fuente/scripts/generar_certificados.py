"""Genera certificados X.509 autofirmados de aplicación para cada componente OPC UA (RF-12, RNF-10).

Componentes: plant_server, gateway, controller, monitor y hmi. Para cada uno se crean
``certs/<componente>_cert.der`` y ``certs/<componente>_key.pem`` con el URI de aplicación
``urn:unipamplona:siddfai:fdisim:<componente>`` y el nombre de host como SubjectAltName, y se
construyen las listas de confianza (``certs/trusted/``) según quién se conecta con quién:

    controller, monitor → gateway → plant_server

Los certificados nunca se versionan (ver .gitignore).

Uso previsto::

    python scripts/generar_certificados.py [--out-dir certs] [--days 365]

Fase de implementación: Fase 1 (prueba de concepto) y Fase 3.
Dependencias previstas: cryptography (o las utilidades de asyncua).
"""

from __future__ import annotations

import argparse

COMPONENTS = ("plant_server", "gateway", "controller", "monitor", "hmi")
TRUST = {  # quién confía en el certificado de quién
    "plant_server": ("gateway",),
    "gateway": ("plant_server", "controller", "monitor", "hmi"),
    "controller": ("gateway",),
    "monitor": ("gateway",),
    "hmi": ("gateway",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default="certs")
    parser.add_argument("--days", type=int, default=365)
    parser.parse_args()
    raise NotImplementedError("Fase 1 — RF-12: generación de certificados de aplicación")


if __name__ == "__main__":
    raise SystemExit(main())
