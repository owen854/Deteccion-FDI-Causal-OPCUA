"""Interfaz de línea de comandos ``fdisim`` (RF-54).

Comandos::

    fdisim run       --scenario config/scenarios/sesgo_lt102.yaml [--mode network|offline]
    fdisim train     --data data/processed/train.parquet --out data/models/causal_v1
    fdisim detect    --run data/raw/<run_id>
    fdisim campaign  --campaign config/campaigns/campana_oe4.yaml
    fdisim report    --campaign-dir results/campana_oe4
    fdisim ui        [--host 127.0.0.1] [--port 8080]
    fdisim certs     [--out-dir certs]

Los comandos cuya funcionalidad aún no existe informan la fase en la que se implementan y
terminan con código 2.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from fdisim import __version__
from fdisim.common import paths


def _cmd_run(args: argparse.Namespace) -> int:
    if args.mode == "offline":
        from fdisim.orchestration.offline import run_scenario_offline

        run_dir = run_scenario_offline(Path(args.scenario), Path(args.config), args.seed)
    else:
        from fdisim.orchestration.runtime import run_scenario_network

        run_dir = run_scenario_network(Path(args.scenario), Path(args.config), args.seed, args.ui)
    print(f"Corrida guardada en {run_dir}")
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    raise NotImplementedError("Fase 5 — RF-28..RF-32: construcción del modelo causal")


def _cmd_detect(args: argparse.Namespace) -> int:
    raise NotImplementedError("Fase 6 — RF-38: detección fuera de línea")


def _cmd_campaign(args: argparse.Namespace) -> int:
    from fdisim.evaluation.campaign import run_campaign

    out = run_campaign(Path(args.campaign))
    print(f"Resultados en {out}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from fdisim.evaluation.report import build_report

    print(f"Reporte: {build_report(Path(args.campaign_dir))}")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from fdisim.ui.app import run_ui

    run_ui(args.host, args.port, args.config)
    return 0


def _cmd_certs(args: argparse.Namespace) -> int:
    raise NotImplementedError(
        "Fase 1/3 — RF-12: generación de certificados (scripts/generar_certificados.py)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdisim",
        description="FDISim-OPCUA: simulación de detección de inyección de datos falsos en OPC UA "
        "mediante análisis causal.",
    )
    parser.add_argument("--version", action="version", version=f"fdisim {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(
        name: str, help_: str, handler: Callable[[argparse.Namespace], int]
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_)
        p.add_argument(
            "--config", default=str(paths.DEFAULT_CONFIG), help="configuración global YAML"
        )
        p.set_defaults(handler=handler)
        return p

    p = add("run", "Ejecuta un escenario (co-simulación en red u offline)", _cmd_run)
    p.add_argument("--scenario", required=True, help="archivo de escenario YAML")
    p.add_argument("--mode", choices=["network", "offline"], default="network")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--ui", action="store_true", help="abrir la HMI durante la corrida")

    p = add("train", "Construye el modelo causal con datos de operación normal", _cmd_train)
    p.add_argument("--data", required=True)
    p.add_argument("--out", default=str(paths.MODELS_DIR / "causal_v1"))

    p = add("detect", "Reprocesa una corrida guardada con los detectores", _cmd_detect)
    p.add_argument("--run", required=True)

    p = add("campaign", "Ejecuta una campaña experimental (OE4)", _cmd_campaign)
    p.add_argument("--campaign", required=True)

    p = add("report", "Genera el reporte de una campaña", _cmd_report)
    p.add_argument("--campaign-dir", required=True)

    p = add("ui", "Inicia la HMI web local", _cmd_ui)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)

    p = add("certs", "Genera certificados X.509 de aplicación para los componentes", _cmd_certs)
    p.add_argument("--out-dir", default=str(paths.CERTS_DIR))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except NotImplementedError as exc:
        print(f"[fdisim] Funcionalidad pendiente: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
