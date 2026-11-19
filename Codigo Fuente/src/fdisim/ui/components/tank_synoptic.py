"""Sinóptico SVG de los dos tanques con niveles, bomba, caudal y consigna (RF-47).

Dibuja el proceso en cascada: la bomba P-101 eleva el agua al tanque 1 (arriba), el tanque 1
descarga por gravedad en el tanque 2 (abajo) y el tanque 2 descarga al drenaje. Los niveles se
rellenan en proporción a su rango (0–50 cm) y la consigna se marca con una línea discontinua en
el tanque 2. ``render_svg`` es una función pura (se prueba sin navegador); ``tank_synoptic``
crea el elemento y devuelve su función de refresco.

Implementado en la Fase 3 (HMI v0).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102
from fdisim.ui.state import UiState

H_MAX = 50.0
TANK_W, TANK_H = 120.0, 120.0
T1 = (170.0, 30.0)  # esquina superior izquierda del tanque 1
T2 = (330.0, 200.0)  # esquina superior izquierda del tanque 2
WATER = "#3b82f6"
STEEL = "#334155"
TEXT = "#0f172a"
MUTED = "#475569"
ACCENT = "#dc2626"


def _fmt(value: float, unit: str, digits: int = 2) -> str:
    return "—" if not math.isfinite(value) else f"{value:.{digits}f} {unit}"


def _fill(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value / H_MAX)) * TANK_H


def _tank(x: float, y: float, level: float, name: str, tag: str) -> str:
    fill = _fill(level)
    return (
        f'<rect x="{x}" y="{y + TANK_H - fill:.1f}" width="{TANK_W}" height="{fill:.1f}" '
        f'fill="{WATER}" opacity="0.75"/>'
        f'<rect x="{x}" y="{y}" width="{TANK_W}" height="{TANK_H}" fill="none" '
        f'stroke="{STEEL}" stroke-width="3"/>'
        f'<text x="{x + TANK_W + 10}" y="{y + 16}" font-size="14" font-weight="bold" '
        f'fill="{TEXT}">{name}</text>'
        f'<text x="{x + TANK_W + 10}" y="{y + 36}" font-size="13" fill="{TEXT}">'
        f"{tag} {_fmt(level, 'cm')}</text>"
    )


def render_svg(values: dict[str, float]) -> str:
    h1 = values.get(LT_101, math.nan)
    h2 = values.get(LT_102, math.nan)
    sp = values.get(SP_102, math.nan)
    q = values.get(FT_101, math.nan)
    u = values.get(P_101, math.nan)
    (x1, y1), (x2, y2) = T1, T2
    pump_x, pump_y = 70.0, 320.0
    parts = [
        '<svg viewBox="0 0 560 360" width="100%" role="img" aria-label="Sinóptico de la planta">',
        # bomba → tanque 1 (entra por arriba)
        f'<polyline points="{pump_x},{pump_y - 22} {pump_x},12 {x1 + 30},12 {x1 + 30},{y1}" '
        f'fill="none" stroke="{STEEL}" stroke-width="4"/>',
        f'<circle cx="{pump_x}" cy="{pump_y}" r="22" fill="#e2e8f0" stroke="{STEEL}" '
        'stroke-width="3"/>',
        f'<polygon points="{pump_x - 8},{pump_y - 10} {pump_x - 8},{pump_y + 10} '
        f'{pump_x + 12},{pump_y}" fill="{STEEL}"/>',
        f'<text x="{pump_x + 30}" y="{pump_y + 5}" font-size="13" fill="{TEXT}">'
        f"P-101 {_fmt(u, '%', 1)}</text>",
        f'<text x="{pump_x + 30}" y="{pump_y - 18}" font-size="12" fill="{MUTED}">'
        f"FT-101 {_fmt(q, 'cm³/s', 1)}</text>",
        # tanque 1 → tanque 2 por gravedad (sale por abajo, entra por arriba)
        f'<polyline points="{x1 + TANK_W / 2},{y1 + TANK_H} {x1 + TANK_W / 2},{y2 - 25} '
        f'{x2 + 30},{y2 - 25} {x2 + 30},{y2}" fill="none" stroke="{STEEL}" stroke-width="4"/>',
        _tank(x1, y1, h1, "Tanque 1", "LT-101"),
        _tank(x2, y2, h2, "Tanque 2", "LT-102"),
        # descarga del tanque 2
        f'<polyline points="{x2 + TANK_W / 2},{y2 + TANK_H} {x2 + TANK_W / 2},{y2 + TANK_H + 22}" '
        f'fill="none" stroke="{STEEL}" stroke-width="4"/>',
        f'<polygon points="{x2 + TANK_W / 2 - 7},{y2 + TANK_H + 20} '
        f'{x2 + TANK_W / 2 + 7},{y2 + TANK_H + 20} {x2 + TANK_W / 2},{y2 + TANK_H + 32}" '
        f'fill="{STEEL}"/>',
    ]
    if math.isfinite(sp):
        y_sp = y2 + TANK_H - _fill(sp)
        parts.append(
            f'<line x1="{x2 - 8}" y1="{y_sp:.1f}" x2="{x2 + TANK_W + 8}" y2="{y_sp:.1f}" '
            f'stroke="{ACCENT}" stroke-width="2" stroke-dasharray="6 4"/>'
            f'<text x="{x2 + TANK_W + 10}" y="{y_sp + 4:.1f}" font-size="12" fill="{ACCENT}">'
            f"SP {_fmt(sp, 'cm', 1)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def tank_synoptic(state: UiState) -> Callable[[], None]:
    """Crea el sinóptico en la página actual y devuelve su función de refresco."""
    from nicegui import ui

    tags = (LT_101, LT_102, FT_101, P_101, SP_102)
    html = ui.html(render_svg({}), sanitize=False).classes("w-full")

    def refresh() -> None:
        html.set_content(render_svg({tag: state.value(tag) for tag in tags}))

    return refresh
