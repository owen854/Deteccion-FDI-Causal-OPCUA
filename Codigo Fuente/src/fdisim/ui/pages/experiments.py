"""Página «Experimentos» (``/experimentos``): escenario en curso, ataques programados y
activación interactiva de ataques (RF-48, RF-23).

La HMI no habla con el gateway para esto: envía la orden al orquestador por el canal local
del plano de experimento (``common.experiment_channel``), que la reenvía al gateway. El ataque
empieza en el tiempo simulado actual (≤ 1 s tras la orden) y queda etiquetado como cualquier
otro. Solo está disponible si la corrida se inició con ``fdisim run --ui``.

Implementado en la Fase 4 (versión inicial; se amplía en la Fase 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, AttackType
from fdisim.ui.state import UiState

TARGETS = (LT_102, LT_101, FT_101, P_101)
ENVELOPES: Mapping[str, tuple[float, float]] = {
    LT_101: (2.0, 45.0),
    LT_102: (2.0, 45.0),
    FT_101: (0.0, 150.0),
    P_101: (0.0, 100.0),
}
RATES: Mapping[str, float] = {LT_101: 0.5, LT_102: 0.5, FT_101: 2.0, P_101: 2.0}
TYPE_LABELS = {"bias": "Sesgo", "ramp": "Rampa", "replay": "Repetición (replay)"}


def attack_request(
    kind: str,
    target: str,
    duration_s: float,
    *,
    bias: float = 2.0,
    slope_per_s: float = 0.01,
    max_deviation: float = 5.0,
    record_s: float = 60.0,
    stealth: bool = True,
) -> dict[str, Any]:
    """Diccionario del ataque que la HMI envía al orquestador (parámetros según el tipo)."""
    AttackType(kind)  # valida el tipo
    params = {
        "bias": {"bias": bias},
        "ramp": {"slope_per_s": slope_per_s, "max_deviation": max_deviation},
        "replay": {"record_s": record_s},
    }[kind]
    stealth_cfg: dict[str, Any] = {"enabled": bool(stealth) and kind != "replay"}
    if stealth_cfg["enabled"]:
        stealth_cfg["envelope"] = list(ENVELOPES[target])
        stealth_cfg["max_rate_per_s"] = RATES[target]
    return {
        "type": kind,
        "targets": [target],
        "duration_s": float(duration_s),
        "params": params,
        "stealth": stealth_cfg,
    }


def attack_rows(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Filas de la tabla de ataques: los del escenario y los armados, con su estado."""
    now = float(status.get("sim_time") or 0.0)
    executed = {e["attack_id"]: e for e in status.get("events", [])}
    rows = []
    for item in status.get("scenario_attacks", []):
        start, end = float(item["start_s"]), float(item["start_s"]) + float(item["duration_s"])
        rows.append(
            _row(
                item["id"],
                item["type"],
                item["targets"],
                start,
                end,
                item["params"],
                executed.get(item["id"]),
                now,
            )
        )
    for aid, event in executed.items():
        if any(r["id"] == aid for r in rows):
            continue
        end = event["t_end"] if event["t_end"] is not None else None
        rows.append(
            _row(
                aid,
                event["type"],
                event["targets"],
                event["t_start"],
                end,
                event["params"],
                event,
                now,
            )
        )
    return rows


def _row(
    aid: str,
    kind: str,
    targets: list[str],
    start: float,
    end: float | None,
    params: Mapping[str, Any],
    event: Mapping[str, Any] | None,
    now: float,
) -> dict[str, Any]:
    if event is not None and event.get("t_end") is not None:
        state, end = "terminado", float(event["t_end"])
    elif event is not None or (start <= now and (end is None or now < end)):
        state = "activo"
    else:
        state = "programado" if now < start else "terminado"
    return {
        "id": aid,
        "tipo": TYPE_LABELS.get(kind, kind),
        "objetivo": ", ".join(targets),
        "ventana": f"{start:.0f} – {end:.0f} s" if end is not None else f"desde {start:.0f} s",
        "parametros": ", ".join(f"{k} = {v:g}" for k, v in params.items()),
        "estado": state,
    }


def register(state: UiState, link: Any = None, client: Any = None) -> None:
    from nicegui import run, ui

    from fdisim.ui.components.header import page_header

    @ui.page("/experimentos")
    def page() -> None:
        ui.page_title("FDISim-OPCUA · Experimentos")
        ui.query("body").style("background-color: #f1f5f9")
        refresh_header = page_header("Experimentos", state, link)

        if client is None:
            with ui.card().classes("w-full"):
                ui.label("Ataques interactivos no disponibles").classes("font-bold")
                ui.label(
                    "Para armar ataques en caliente, inicie la corrida con la HMI: "
                    "fdisim run --scenario config/scenarios/normal.yaml --ui"
                )
            ui.timer(1.0, refresh_header)
            return

        with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
            with ui.card().classes("w-1/3"):
                ui.label("Armar un ataque (gateway comprometido)").classes("font-bold")
                kind = ui.select(TYPE_LABELS, label="Tipo", value="bias").classes("w-full")
                target = ui.select(list(TARGETS), label="Variable objetivo", value=LT_102).classes(
                    "w-full"
                )
                duration = ui.number("Duración [s simulados]", value=120, min=1, step=10)
                bias = ui.number("Sesgo b", value=2.0, step=0.5)
                slope = ui.number("Pendiente r [unidades/s]", value=0.01, step=0.005, format="%.3f")
                max_dev = ui.number("Desviación máxima", value=5.0, step=0.5)
                record = ui.number("Grabación del replay [s]", value=60, min=5, step=5)
                stealth = ui.switch("Sigilo (envolvente y tasa limitada)", value=True)
                bias.bind_visibility_from(kind, "value", lambda v: v == "bias")
                slope.bind_visibility_from(kind, "value", lambda v: v == "ramp")
                max_dev.bind_visibility_from(kind, "value", lambda v: v == "ramp")
                record.bind_visibility_from(kind, "value", lambda v: v == "replay")
                stealth.bind_visibility_from(kind, "value", lambda v: v != "replay")

                async def arm() -> None:
                    request = attack_request(
                        kind.value,
                        target.value,
                        duration.value or 60,
                        bias=bias.value or 0.0,
                        slope_per_s=slope.value or 0.0,
                        max_deviation=max_dev.value or 0.0,
                        record_s=record.value or 60,
                        stealth=stealth.value,
                    )
                    reply = await run.io_bound(client.arm, request)
                    if reply.get("ok"):
                        ui.notify(f"Ataque {reply['attack_id']} armado", type="warning")
                    else:
                        ui.notify(reply.get("error", "No se pudo armar"), type="negative")

                ui.button("Armar ahora", on_click=arm, color="red").classes("w-full")

            with ui.card().classes("w-2/3"):
                summary = ui.label().classes("font-bold")
                columns = [
                    {"name": key, "label": label, "field": key, "align": "left"}
                    for key, label in (
                        ("id", "Id"),
                        ("tipo", "Tipo"),
                        ("objetivo", "Objetivo"),
                        ("ventana", "Ventana"),
                        ("parametros", "Parámetros"),
                        ("estado", "Estado"),
                    )
                ]
                table = ui.table(rows=[], columns=columns, row_key="id").classes("w-full")
                with ui.row().classes("items-center gap-2"):
                    to_disarm = ui.select([], label="Ataque activo").classes("w-48")

                    async def disarm() -> None:
                        if not to_disarm.value:
                            return
                        reply = await run.io_bound(client.disarm, to_disarm.value)
                        ui.notify(
                            f"Ataque {to_disarm.value} desarmado"
                            if reply.get("ok")
                            else reply.get("error", "Error")
                        )

                    ui.button("Desarmar", on_click=disarm)

        async def refresh() -> None:
            refresh_header()
            status = await run.io_bound(client.status)
            if not status.get("ok"):
                summary.text = status.get("error", "Sin corrida activa")
                return
            rows = attack_rows(status)
            summary.text = (
                f"Escenario «{status['scenario']}» · t = {status['sim_time']:.1f} s · "
                f"{sum(r['estado'] == 'activo' for r in rows)} ataque(s) activo(s)"
            )
            table.rows = rows
            table.update()
            to_disarm.options = [r["id"] for r in rows if r["estado"] == "activo"]
            to_disarm.update()

        ui.timer(1.0, refresh)
