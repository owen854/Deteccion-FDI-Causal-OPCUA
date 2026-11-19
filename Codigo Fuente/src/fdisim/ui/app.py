"""Punto de entrada de la HMI web (RF-47 a RF-52).

Páginas (``ui/pages``):

- ``/``              Operación: sinóptico de tanques, tendencias y consigna (RF-47, RF-09).
- ``/experimentos``  Escenarios, parámetros, ataques interactivos (RF-48, RF-23).
- ``/deteccion``     Residuos, umbrales y alarmas causal vs. base (RF-49).
- ``/grafo``         Grafo causal con resaltado de inconsistencias (RF-50).
- ``/resultados``    Métricas y comparativas de campañas (RF-51).
- ``/comunicacion``  Endpoints, seguridad, sesiones y latencias (RF-52).

La HMI es un cliente OPC UA del gateway (``ui.link``). Se inicia sola con ``fdisim ui`` (se
conecta a la co-simulación que esté corriendo y espera si no hay ninguna) o junto con una corrida
con ``fdisim run --ui``.

Fase 3: HMI v0 con la página de operación. Las demás páginas llegan en la Fase 7.
Dependencia: NiceGUI.
"""

from __future__ import annotations

from datetime import datetime

PAGES: dict[str, str] = {
    "/": "fdisim.ui.pages.operation",
    "/experimentos": "fdisim.ui.pages.experiments",
    "/deteccion": "fdisim.ui.pages.detection",
    "/grafo": "fdisim.ui.pages.causal_model",
    "/resultados": "fdisim.ui.pages.results",
    "/comunicacion": "fdisim.ui.pages.communication",
}
IMPLEMENTED_PAGES = ("/",)


def run_ui(
    host: str | None = None,
    port: int | None = None,
    config_path: str | None = None,
    *,
    run_id: str | None = None,
    show: bool = True,
) -> None:
    """Registra las páginas y arranca el servidor NiceGUI (bloqueante)."""
    from nicegui import app, ui

    from fdisim.common.config import load_config
    from fdisim.common.logging_setup import configure_logging
    from fdisim.ui.link import HmiLink
    from fdisim.ui.pages import operation
    from fdisim.ui.state import UiState

    config = load_config(config_path).to_dict()
    ui_cfg = config.get("ui", {})
    logger = configure_logging(
        "hmi",
        run_id or f"{datetime.now():%Y%m%d-%H%M%S}_hmi",
        str(config.get("logging", {}).get("level", "INFO")),
        config.get("logging", {}).get("dir"),
    )
    state = UiState()
    link = HmiLink(config, state, logger)
    app.on_startup(link.start)
    app.on_shutdown(link.stop)
    operation.register(state, link, config)
    ui.run(
        host=host or str(ui_cfg.get("host", "127.0.0.1")),
        port=int(port or ui_cfg.get("port", 8080)),
        title="FDISim-OPCUA",
        reload=False,
        show=show,
        show_welcome_message=False,
        favicon="💧",
    )
