"""Encabezado común de la HMI: navegación, conexión, tiempo simulado, seguridad y alarmas.

El indicador de alarma (RNF-15) se ve en todas las páginas: rojo con la variable sospechosa
mientras el detector causal está en alarma, ámbar si solo alarma el método base y verde si no
hay alarmas. Se refresca con la página (≥ 2 Hz), así que una alarma aparece en menos de 1 s.

Implementado en la Fase 4; navegación completa e indicador de alarmas en la Fase 7.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from fdisim.opcua.plant_server import SIM_RUNNING, SIM_TIME
from fdisim.ui.state import UiState

NAVIGATION = (
    ("/", "Operación"),
    ("/experimentos", "Experimentos"),
    ("/deteccion", "Detección"),
    ("/grafo", "Grafo causal"),
    ("/resultados", "Resultados"),
    ("/comunicacion", "Comunicaciones"),
)


def alarm_banner(state: UiState) -> tuple[str, str]:
    """Texto y color del indicador de alarmas (rojo: causal, ámbar: solo base, verde: no)."""
    causal = state.active_alarm("causal")
    base = state.active_alarm("threshold")
    if causal is not None:
        suspect = causal.get("suspected") or "—"
        return f"⚠ ALARMA causal · sospechosa {suspect}", "bg-red-600"
    if base is not None:
        return f"⚠ Alarma del método base · {base.get('suspected') or '—'}", "bg-amber-500"
    if state.det_latest:
        return "✓ Sin alarmas", "bg-green-700"
    return "Detección inactiva", "bg-slate-600"


def page_header(title: str, state: UiState, link: object) -> Callable[[], None]:
    """Crea el encabezado y devuelve su función de refresco."""
    from nicegui import ui

    security = link.security  # type: ignore[attr-defined]
    with ui.header().classes("items-center justify-between bg-slate-800 gap-2"):
        with ui.row().classes("items-center gap-5"):
            ui.label(f"FDISim-OPCUA · {title}").classes("text-lg font-bold")
            for target, label in NAVIGATION:
                ui.link(label, target).classes("text-white opacity-80 text-sm")
        with ui.row().classes("items-center gap-4"):
            alarm = ui.label().classes("text-sm font-bold px-2 py-1 rounded")
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
        text, color = alarm_banner(state)
        alarm.text = text
        alarm.classes(replace=f"text-sm font-bold px-2 py-1 rounded text-white {color}")

    return refresh
