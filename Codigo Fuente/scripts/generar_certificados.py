"""Genera la PKI local del proyecto: certificados X.509 de aplicación, listas de confianza y
credenciales de prueba (RF-12, RNF-10).

Para cada componente (plant_server, gateway, controller, monitor, hmi) crea
``certs/<componente>/cert.der`` y ``key.pem`` con el URI
``urn:unipamplona:siddfai:fdisim:<componente>`` y, según quién habla con quién, copia los
certificados de los pares en ``certs/<componente>/trusted/``::

    controller, monitor, hmi → gateway → plant_server

También crea ``certs/credenciales.json`` con usuarios y contraseñas aleatorias para los
clientes (incluido ``uaexpert`` para las pruebas de interoperabilidad). Nada de esto se
versiona.

Uso::

    python scripts/generar_certificados.py              # crea lo que falte
    python scripts/generar_certificados.py --forzar     # regenera todos los certificados
    python scripts/generar_certificados.py --dias 730
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fdisim.common import paths  # noqa: E402
from fdisim.opcua.security import (  # noqa: E402
    COMPONENTS,
    build_trust_lists,
    create_credentials,
    generate_application_certificate,
    pki_paths,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera certificados y credenciales OPC UA.")
    parser.add_argument("--dir", default=str(paths.CERTS_DIR), help="carpeta de la PKI")
    parser.add_argument("--dias", type=int, default=365, help="validez de los certificados")
    parser.add_argument("--forzar", action="store_true", help="regenerar aunque existan")
    args = parser.parse_args(argv)

    certs_dir = Path(args.dir)
    print(f"PKI en {paths.resolve(certs_dir)}")
    for component in COMPONENTS:
        pki = pki_paths(component, certs_dir)
        if pki.exists() and not args.forzar:
            print(f"  [existe]  {component}")
            continue
        generate_application_certificate(component, certs_dir, days=args.dias)
        print(f"  [creado]  {component}  ({pki.cert.name}, {pki.key.name})")

    trust = build_trust_lists(certs_dir)
    print("Listas de confianza:")
    for component, peers in trust.items():
        print(f"  {component:<13} confía en: {', '.join(peers) or '—'}")

    cred = create_credentials(certs_dir)
    print(f"Credenciales de prueba: {cred} (no se versiona; no compartir fuera del laboratorio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
