"""Página «Operación» (``/``): sinóptico de los tanques, tendencias y consigna (RF-47, RF-09).

HMI v0 (Fase 3): estado de la conexión con el gateway y de la simulación, sinóptico de los
tanques, cambio de consigna y tendencias de niveles, consigna, bomba y caudal. Todo lo que se
muestra llegó por OPC UA a través del gateway, como en la sala de control de una planta real.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102
from fdisim.ui.components.header import page_header
from fdisim.ui.components.tank_synoptic import tank_synoptic
from fdisim.ui.components.trend_chart import trend_chart
from fdisim.ui.link import HmiLink
from fdisim.ui.state import UiState


def register(
    state: UiState, link: HmiLink | None = None, config: Mapping[str, Any] | None = None
) -> None:
    from nicegui import ui

    if link is None:
        raise ValueError("La página de operación necesita el enlace OPC UA de la HMI")
    refresh_hz = float((config or {}).get("ui", {}).get("refresh_hz", 4))

    @ui.page("/")
    def page() -> None:
        ui.page_title("FDISim-OPCUA · Operación")
        ui.query("body").style("background-color: #f1f5f9")
        refresh_header = page_header("Operación", state, link)

        with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
            with ui.card().classes("w-3/5"):
                ui.label("Sinóptico").classes("font-bold")
                refresh_synoptic = tank_synoptic(state)
            with ui.card().classes("w-2/5"):
                ui.label("Consigna del nivel del tanque 2 (LIC-102.SP)").classes("font-bold")
                current = ui.label()
                target = ui.number(
                    "Nueva consigna [cm]", value=25.0, min=5, max=45, step=0.5, format="%.1f"
                ).classes("w-full")

                async def apply() -> None:
                    if target.value is None:
                        ui.notify("Indique un valor", type="warning")
                        return
                    message = await link.write_setpoint(float(target.value))
                    ui.notify(
                        message, type="positive" if message.startswith("Consigna") else "warning"
                    )

                ui.button("Aplicar consigna", on_click=apply).classes("w-full")
                ui.separator()
                ui.label("Valores recibidos del gateway").classes("font-bold")
                values = ui.label().classes("font-mono whitespace-pre text-sm")

        with ui.card().classes("w-full"):
            refresh_levels = trend_chart(
                state,
                [LT_101, LT_102, SP_102],
                "Niveles y consigna (sombreado: ataque)",
                show_attack_bands=True,
                y_name="cm",
            )
        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.card().classes("w-1/2"):
                refresh_pump = trend_chart(state, [P_101], "Comando de la bomba", y_name="%")
            with ui.card().classes("w-1/2"):
                refresh_flow = trend_chart(state, [FT_101], "Caudal de entrada", y_name="cm³/s")

        def refresh_fast() -> None:
            refresh_header()
            sp = state.value(SP_102)
            current.text = (
                f"Consigna actual: {sp:.2f} cm" if math.isfinite(sp) else "Consigna actual: —"
            )
            lines = []
            for tag in (LT_101, LT_102, FT_101, P_101, SP_102):
                sample = state.latest.get(tag)
                lines.append(
                    f"{tag:<11} {sample.value:9.3f}  {sample.status}"
                    if sample
                    else f"{tag:<11}         —"
                )
            values.text = "\n".join(lines)
            refresh_synoptic()

        def refresh_slow() -> None:
            refresh_levels()
            refresh_pump()
            refresh_flow()

        ui.timer(1.0 / refresh_hz, refresh_fast)
        ui.timer(1.0, refresh_slow)
