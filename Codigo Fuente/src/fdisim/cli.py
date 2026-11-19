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
    from fdisim.common.config import ConfigError

    if args.mode == "offline":
        from fdisim.orchestration.offline import run_scenario_offline

        try:
            run_dir = run_scenario_offline(
                Path(args.scenario),
                Path(args.config),
                args.seed,
                duration_s=args.duracion,
                integrator=args.integrador,
            )
        except ConfigError as exc:
            print(f"[fdisim] No se inició la corrida: {exc}", file=sys.stderr)
            return 1
        print(f"[fdisim] Corrida offline guardada en {run_dir}")
        _print_summary(run_dir)
        return 0

    from fdisim.orchestration.runtime import PortInUseError, run_scenario_network

    try:
        run_dir = run_scenario_network(
            Path(args.scenario),
            Path(args.config),
            args.seed,
            args.ui,
            duration_s=args.duracion,
            time_scale=args.escala,
            progress=lambda msg: print(f"[fdisim] {msg}", flush=True),
            open_browser=not args.no_abrir,
        )
    except KeyboardInterrupt:
        print("[fdisim] Corrida interrumpida; los datos parciales quedaron guardados.")
        return 130
    except (ConfigError, PortInUseError) as exc:
        print(f"[fdisim] No se inició la corrida: {exc}", file=sys.stderr)
        return 1
    _print_summary(run_dir)
    return 0


def _print_summary(run_dir: Path) -> None:
    import json

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    lat = summary.get("latency_ms", {}).get("end_to_end", {})
    if lat.get("n"):
        print(
            f"Latencia planta → gateway → monitor: p50 {lat['p50']:.0f} ms, "
            f"p95 {lat['p95']:.0f} ms, máx {lat['max']:.0f} ms"
        )
    for tag, item in summary.get("completeness", {}).items():
        print(f"Completitud {tag}: {item['received']}/{item['expected']} ({item['pct']:.2f} %)")
    if summary.get("mode") == "offline":
        sim = summary["simulation"]
        print(f"Simulación: {sim['steps']} pasos a {sim['speedup']:.0f}× el tiempo real")
    for effect in summary.get("attack_effects", []):
        detail = {
            "bias": lambda e: f"diferencia mediana {e.get('median_diff', float('nan')):+.3f}",
            "ramp": lambda e: (
                f"pendiente {e.get('slope', float('nan')):.4f}/s, R² {e.get('r2', 0):.4f}"
            ),
            "replay": lambda e: f"{100 * e.get('replayed_fraction', 0):.1f} % repetido",
        }[effect["type"]](effect)
        print(
            f"Ataque {effect['attack_id']} ({effect['type']} sobre {effect['tag']}, "
            f"[{effect['t_start']:.0f}, {effect['t_end']:.0f}) s): {detail}"
        )
    for name, ok in summary.get("criteria", {}).items():
        mark = "--" if ok is None else ("OK" if ok else "NO")
        note = " (no aplica en esta corrida)" if ok is None else ""
        print(f"  [{mark}] {name}{note}")


def _cmd_dataset(args: argparse.Namespace) -> int:
    from fdisim.data.dataset import generate_datasets

    attacks = (
        [Path(p) for p in args.ataques]
        if args.ataques
        else sorted(
            p
            for p in paths.SCENARIOS_DIR.glob("*.yaml")
            if p.stem not in ("normal", "escalon_consigna")
        )
    )
    manifest = generate_datasets(
        Path(args.out),
        config_path=Path(args.config),
        normal_scenario=Path(args.normal),
        attack_scenarios=attacks,
        n_train=args.entrenamiento,
        n_val=args.validacion,
        n_test_normal=args.prueba,
        n_per_attack=args.por_ataque,
        base_seed=args.semilla,
        duration_s=args.duracion,
        integrator=args.integrador,
        progress=lambda msg: print(f"[fdisim] {msg}", flush=True),
    )
    import json

    data = json.loads(manifest.read_text(encoding="utf-8"))
    for split, info in data["splits"].items():
        print(
            f"  {split:<5} {info['runs']:>3} corridas, {info['rows']:>7} filas, "
            f"{info['attack_rows']:>6} bajo ataque"
        )
    print(f"Dataset guardado en {manifest.parent} (manifiesto: {manifest.name})")
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    import json

    from fdisim.causal.training import train_causal_model

    data = Path(args.data)
    if not data.is_file():
        print(
            f"[fdisim] No existe el dataset {data}. Genérelo con: fdisim dataset", file=sys.stderr
        )
        return 1
    manifest = train_causal_model(
        data,
        Path(args.out),
        val_path=Path(args.val) if args.val else None,
        config_path=Path(args.config),
        tau_max=args.tau_max,
        alpha=args.alpha,
        coarse_block=args.bloque,
        with_sensitivity=not args.sin_sensibilidad,
        progress=lambda msg: print(f"[fdisim] {msg}", flush=True),
    )
    info = json.loads(manifest.read_text(encoding="utf-8"))
    rmse = info["validation_rmse"]
    for tag, value in rmse["physics_informed"].items():
        limit = rmse["limit_2sigma"].get(tag)
        print(f"  RMSE {tag}: {value:.4f}" + (f" (límite {limit:.2f})" if limit else ""))
    for name, ok in info["criteria"].items():
        print(f"  [{'OK' if ok else 'NO'}] {name}")
    print(f"Reporte: {manifest.parent / 'report.md'}")
    return 0


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

    run_ui(args.host, args.port, args.config, run_id=args.run_id, show=not args.no_abrir)
    return 0


def _cmd_certs(args: argparse.Namespace) -> int:
    from fdisim.opcua.security import find_uaexpert_certificate, setup_pki, trust_certificate

    result = setup_pki(args.out_dir, days=args.dias, force=args.forzar)
    print(f"PKI en {paths.resolve(args.out_dir)}")
    print(f"  Certificados creados: {', '.join(result['created']) or 'ninguno (ya existían)'}")
    for component, peers in result["trust"].items():
        print(f"  {component:<13} confía en: {', '.join(peers) or '—'}")
    print(f"  Credenciales de prueba: {result['credentials']} (no se versiona)")
    if args.confiar_uaexpert:
        cert = find_uaexpert_certificate()
        if cert is None:
            print("No se encontró el certificado de UaExpert: ábralo una vez y repita el comando.")
            return 1
        for target in trust_certificate(
            cert, args.out_dir, ("plant_server", "gateway"), "uaexpert"
        ):
            print(f"  UaExpert agregado a {target}")
    return 0


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
    p.add_argument(
        "--no-abrir", action="store_true", help="con --ui: no abrir el navegador automáticamente"
    )
    p.add_argument(
        "--duracion",
        type=float,
        default=None,
        help="segundos simulados (por defecto, el escenario)",
    )
    p.add_argument(
        "--escala", type=float, default=None, help="factor de tiempo (1 = tiempo real, 5 = 5×)"
    )
    p.add_argument(
        "--integrador", choices=["solve_ivp", "rk4"], default=None, help="solo en modo offline"
    )

    p = add(
        "dataset",
        "Genera por lotes los datasets de entrenamiento, validación y prueba",
        _cmd_dataset,
    )
    p.add_argument("--out", default=str(paths.PROCESSED_DIR / "v1"), help="carpeta de salida")
    p.add_argument("--normal", default=str(paths.SCENARIOS_DIR / "normal.yaml"))
    p.add_argument(
        "--ataques",
        nargs="*",
        default=None,
        help="escenarios con ataque (por defecto, todos los del catálogo)",
    )
    p.add_argument("--entrenamiento", type=int, default=10, help="corridas normales")
    p.add_argument("--validacion", type=int, default=3, help="corridas normales")
    p.add_argument("--prueba", type=int, default=3, help="corridas normales en prueba")
    p.add_argument("--por-ataque", type=int, default=2, help="corridas por escenario de ataque")
    p.add_argument("--semilla", type=int, default=1000, help="semilla base")
    p.add_argument("--duracion", type=float, default=None)
    p.add_argument("--integrador", choices=["solve_ivp", "rk4"], default=None)

    p = add("train", "Construye el modelo causal con datos de operación normal", _cmd_train)
    p.add_argument("--data", required=True, help="train.parquet del dataset")
    p.add_argument("--val", default=None, help="por defecto, val.parquet junto a --data")
    p.add_argument("--out", default=str(paths.MODELS_DIR / "causal_v1"))
    p.add_argument("--tau-max", type=int, default=3, help="retardo máximo del descubrimiento")
    p.add_argument("--alpha", type=float, default=0.01, help="nivel de significancia")
    p.add_argument(
        "--bloque", type=int, default=10, help="muestras por bloque en la resolución agregada"
    )
    p.add_argument(
        "--sin-sensibilidad", action="store_true", help="omitir el análisis de sensibilidad"
    )

    p = add("detect", "Reprocesa una corrida guardada con los detectores", _cmd_detect)
    p.add_argument("--run", required=True)

    p = add("campaign", "Ejecuta una campaña experimental (OE4)", _cmd_campaign)
    p.add_argument("--campaign", required=True)

    p = add("report", "Genera el reporte de una campaña", _cmd_report)
    p.add_argument("--campaign-dir", required=True)

    p = add("ui", "Inicia la HMI web local", _cmd_ui)
    p.add_argument("--host", default=None, help="por defecto, ui.host de la configuración")
    p.add_argument("--port", type=int, default=None, help="por defecto, ui.port")
    p.add_argument("--run-id", default=None, help="corrida a la que pertenece la bitácora")
    p.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")

    p = add("certs", "Genera certificados X.509 de aplicación para los componentes", _cmd_certs)
    p.add_argument("--out-dir", default=str(paths.CERTS_DIR))
    p.add_argument("--dias", type=int, default=365, help="validez de los certificados")
    p.add_argument("--forzar", action="store_true", help="regenerar aunque existan")
    p.add_argument(
        "--confiar-uaexpert",
        action="store_true",
        help="agregar el certificado de UaExpert a la planta y al gateway",
    )

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
