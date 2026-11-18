"""Punto de entrada de la HMI web (RF-47 a RF-52).

Páginas (``ui/pages``):

- ``/``              Operación: sinóptico de tanques y tendencias (RF-47).
- ``/experimentos``  Escenarios, parámetros, ataques interactivos (RF-48, RF-23).
- ``/deteccion``     Residuos, umbrales y alarmas causal vs. base (RF-49).
- ``/grafo``         Grafo causal con resaltado de inconsistencias (RF-50).
- ``/resultados``    Métricas y comparativas de campañas (RF-51).
- ``/comunicacion``  Endpoints, seguridad, sesiones y latencias (RF-52).

Fase de implementación: Fase 7 (incremental desde el Sprint 2). Dependencia: NiceGUI.
"""

from __future__ import annotations

PAGES: dict[str, str] = {
    "/": "fdisim.ui.pages.operation",
    "/experimentos": "fdisim.ui.pages.experiments",
    "/deteccion": "fdisim.ui.pages.detection",
    "/grafo": "fdisim.ui.pages.causal_model",
    "/resultados": "fdisim.ui.pages.results",
    "/comunicacion": "fdisim.ui.pages.communication",
}


def run_ui(host: str = "127.0.0.1", port: int = 8080, config_path: str | None = None) -> None:
    """Registra las páginas y arranca el servidor NiceGUI (bloqueante)."""
    raise NotImplementedError("Fase 7 — RF-47..RF-52: HMI web")
