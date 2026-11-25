"""Tabla de alarmas causal vs. base con estado y variable sospechosa (RF-36, RF-49).

Cada fila es una alarma con su instante, detector, tipo de inconsistencia, variables
implicadas, variable sospechosa, severidad y estado (activa, reconocida o cerrada). El botón
«Reconocer» marca las alarmas seleccionadas como reconocidas.

Implementado en la Fase 7.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fdisim.ui.state import UiState

DETECTORS = {"causal": "Causal", "threshold": "Base"}
KINDS = {
    "residual": "Residuo",
    "cusum": "CUSUM",
    "ewma": "EWMA",
    "structural": "Estructural",
    "limit": "Límite operativo",
    "statistical": "Límite μ ± kσ",
}
STATES = {"active": "activa", "acknowledged": "reconocida", "closed": "cerrada"}


def alarm_rows(state: UiState) -> list[dict[str, Any]]:
    """Filas de la tabla, de la más reciente a la más antigua (función pura)."""
    rows = []
    for alarm_id, alarm in state.alarm_log.items():
        closed = alarm.get("t_end") not in (None, "") or alarm.get("state") == "closed"
        status = "closed" if closed else "active"
        if alarm_id in state.acknowledged or alarm.get("acknowledged"):
            status = "acknowledged" if not closed else "closed"
        t_end = alarm.get("t_end")
        variables = alarm.get("variables") or []
        rows.append(
            {
                "id": alarm_id,
                "detector": DETECTORS.get(str(alarm.get("detector")), alarm.get("detector")),
                "tipo": KINDS.get(str(alarm.get("kind")), alarm.get("kind")),
                "inicio": f"{float(alarm['t']):.1f}",
                "fin": f"{float(t_end):.1f}" if t_end not in (None, "") else "—",
                "variables": ", ".join(variables)
                if isinstance(variables, list)
                else str(variables),
                "sospechosa": alarm.get("suspected_tag") or "—",
                "severidad": f"{float(alarm.get('score') or 0):.1f}",
                "estado": STATES[status],
                "_t": float(alarm["t"]),
            }
        )
    rows.sort(key=lambda r: r["_t"], reverse=True)
    return rows


def alarm_table(state: UiState, on_ack: Callable[[str], Any] | None = None) -> Callable[[], None]:
    """Crea la tabla en la página actual y devuelve su función de refresco."""
    from nicegui import ui

    columns = [
        {"name": key, "label": label, "field": key, "align": "left", "sortable": True}
        for key, label in (
            ("id", "Id"),
            ("detector", "Detector"),
            ("tipo", "Tipo"),
            ("inicio", "Inicio [s]"),
            ("fin", "Fin [s]"),
            ("variables", "Variables"),
            ("sospechosa", "Sospechosa"),
            ("severidad", "Severidad"),
            ("estado", "Estado"),
        )
    ]
    table = ui.table(
        rows=[], columns=columns, row_key="id", selection="multiple", pagination=10
    ).classes("w-full")
    table.add_slot(
        "body-cell-estado",
        """
        <q-td :props="props">
          <q-badge :color="{activa: 'red', reconocida: 'orange'}[props.value] || 'grey'">
            {{ props.value }}
          </q-badge>
        </q-td>
        """,
    )

    async def acknowledge() -> None:
        from nicegui import run

        for row in table.selected:
            if on_ack is not None:
                await run.io_bound(on_ack, row["id"])
            else:
                state.acknowledged.add(row["id"])
        table.selected = []
        refresh()

    ui.button("Reconocer seleccionadas", on_click=acknowledge).props("outline")

    def refresh() -> None:
        rows = alarm_rows(state)
        table.rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        table.update()

    return refresh
