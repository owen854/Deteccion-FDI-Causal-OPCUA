"""Encabezado común de la HMI: título, navegación, conexión, tiempo simulado y seguridad.

Implementado en la Fase 4 (lo comparten las páginas de operación y de experimentos).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from fdisim.opcua.plant_server import SIM_RUNNING, SIM_TIME
from fdisim.ui.state import UiState

NAVIGATION = (("/", "Operación"), ("/experimentos", "Experimentos"))


def page_header(title: str, state: UiState, link: object) -> Callable[[], None]:
    """Crea el encabezado y devuelve su función de refresco."""
    from nicegui import ui

    security = link.security  # type: ignore[attr-defined]
    with ui.header().classes("items-center justify-between bg-slate-800"):
        with ui.row().classes("items-center gap-6"):
            ui.label(f"FDISim-OPCUA · {title}").classes("text-lg font-bold")
            for target, label in NAVIGATION:
                ui.link(label, target).classes("text-white opacity-80 text-sm")
        with ui.row().classes("items-center gap-4"):
            status = ui.label()
            sim = ui.label()
            ui.label(f"{security.mode.value} · {security.policy}").classes("text-sm opacity-80")

    def refresh() -> None:
        connected = link.connected  # type: ignore[attr-defined]
        status.text = "● Conectado al gateway" if connected else "● Sin conexión"
        status.classes(replace="text-green-400" if connected else "text-red-400")
        t = state.value(SIM_TIME)
        running = state.value(SIM_RUNNING, 0.0) > 0.5
        sim.text = (f"t = {t:.1f} s · " if math.isfinite(t) else "") + (
            "En ejecución" if running else "Detenida"
        )

    return refresh
