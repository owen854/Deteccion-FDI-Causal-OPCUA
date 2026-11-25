"""Página «Comunicaciones» (``/comunicacion``): endpoints, modo y política de seguridad,
estado de las sesiones y latencias medidas (RF-52).

- Endpoints de la planta y del gateway (solo localhost o red de laboratorio, RNF-11).
- Seguridad configurada: modo, política, autenticación de usuario y carpeta de la PKI.
- Sesión de la HMI con el gateway: estado y reconexiones.
- Latencia observada por la HMI (recepción − SourceTimestamp) de las últimas muestras: media,
  p50, p95 y máximo. Con intervalos de publicación de 100 y 250 ms la cota de RNF-03 es
  2 × el intervalo de publicación.

Implementado en la Fase 7.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from fdisim.ui.state import UiState


def latency_summary(values: Sequence[float]) -> dict[str, float] | None:
    data = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if data.size == 0:
        return None
    return {
        "n": int(data.size),
        "mean": float(data.mean()),
        "p50": float(np.percentile(data, 50)),
        "p95": float(np.percentile(data, 95)),
        "max": float(data.max()),
    }


def register(state: UiState, link: Any, manager: Any, config: Mapping[str, Any]) -> None:
    from nicegui import ui

    from fdisim.orchestration.components import gateway_endpoint, plant_endpoint
    from fdisim.ui.components.header import page_header

    security = config["opcua"]["security"]
    subscription = config["opcua"]["subscription"]

    @ui.page("/comunicacion")
    def page() -> None:
        ui.page_title("FDISim-OPCUA · Comunicaciones")
        ui.query("body").style("background-color: #f1f5f9")
        refresh_header = page_header("Comunicaciones", state, link)

        with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
            with ui.card().classes("w-1/2"):
                ui.label("Endpoints OPC UA").classes("font-bold")
                for name, url in (
                    ("Servidor de la planta", plant_endpoint(config)),
                    (
                        "Gateway agregador (nodo comprometido en los ataques)",
                        gateway_endpoint(config),
                    ),
                ):
                    ui.label(name).classes("text-sm text-gray-600")
                    ui.label(url).classes("font-mono")
                ui.separator()
                ui.label("Topología").classes("font-bold")
                ui.label(
                    "Planta ⇄ gateway ⇄ {controlador, monitor, HMI}. Cada componente tiene su "
                    "certificado X.509 y usuario propios."
                ).classes("text-sm")
            with ui.card().classes("w-1/2"):
                ui.label("Seguridad configurada (RNF-09)").classes("font-bold")
                for label, value in (
                    ("Modo de seguridad", security.get("mode")),
                    ("Política", security.get("policy")),
                    ("Autenticación de usuario", security.get("user_auth")),
                    ("PKI", security.get("certs_dir")),
                    (
                        "Depuración sin seguridad",
                        "permitida" if security.get("allow_insecure_debug") else "deshabilitada",
                    ),
                    (
                        "Publicación",
                        f"clientes {subscription.get('publishing_interval_ms')} ms · enlace "
                        f"gateway ← planta {subscription.get('gateway_publishing_interval_ms')} ms",
                    ),
                ):
                    with ui.row().classes("w-full justify-between"):
                        ui.label(label).classes("text-sm text-gray-600")
                        ui.label(str(value)).classes("text-sm font-mono")

        with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
            with ui.card().classes("w-1/2"):
                ui.label("Sesión de la HMI con el gateway").classes("font-bold")
                session = ui.label().classes("text-lg")
                reconnections = ui.label().classes("text-sm")
            with ui.card().classes("w-1/2"):
                ui.label("Latencia observada por la HMI (recepción − SourceTimestamp)").classes(
                    "font-bold"
                )
                latency = ui.label().classes("font-mono text-sm whitespace-pre")
                run_info = ui.label().classes("text-sm text-gray-600")

        def refresh() -> None:
            refresh_header()
            connected = link.connected
            session.text = "Conectada (SignAndEncrypt)" if connected else "Sin conexión"
            session.classes(
                replace="text-lg " + ("text-green-700" if connected else "text-red-600")
            )
            reconnections.text = f"Reconexiones de la HMI: {link.client.reconnections}"
            summary = latency_summary(state.latencies_ms)
            latency.text = (
                f"muestras {summary['n']}\nmedia  {summary['mean']:7.1f} ms\n"
                f"p50    {summary['p50']:7.1f} ms\np95    {summary['p95']:7.1f} ms\n"
                f"máx    {summary['max']:7.1f} ms"
                if summary
                else "Sin muestras todavía"
            )
            status = state.run_status
            run_info.text = (
                f"Corrida {status.get('run_id')} · {status.get('time_scale', 1):g}× · "
                f"t = {float(status.get('sim_time', 0)):.1f} s"
                if status.get("ok")
                else "Sin corrida en red activa"
            )

        ui.timer(1.0, refresh)
