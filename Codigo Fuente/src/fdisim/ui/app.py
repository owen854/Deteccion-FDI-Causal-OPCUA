"""Punto de entrada de la HMI web y del aplicativo completo (RF-47 a RF-52).

Páginas (``ui/pages``):

- ``/``              Operación: sinóptico de tanques, tendencias y consigna (RF-47, RF-09).
- ``/experimentos``  Corridas (iniciar y detener), escenarios y ataques interactivos (RF-48, RF-23).
- ``/deteccion``     Residuos, umbrales, acumuladores y alarmas causal vs. base (RF-49).
- ``/grafo``         Grafo causal con resaltado de inconsistencias (RF-50).
- ``/resultados``    Métricas comparativas y exportación (RF-51).
- ``/comunicacion``  Endpoints, seguridad, sesiones y latencias (RF-52).

**Un solo comando.** ``fdisim ui`` (o ``fdisim`` a secas, o el acceso directo
``FDISim.bat``) abre el aplicativo: crea los certificados que falten, genera el modelo causal
si no existe y permite lanzar corridas desde el navegador (``ui.run_manager``). La HMI es
además un cliente OPC UA del gateway (``ui.link``); también se abre junto con una corrida de
consola con ``fdisim run --ui``.

Implementado en la Fase 3 (HMI v0); experimentos en la Fase 4; el resto en la Fase 7.
Dependencia: NiceGUI.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

PAGES: dict[str, str] = {
    "/": "fdisim.ui.pages.operation",
    "/experimentos": "fdisim.ui.pages.experiments",
    "/deteccion": "fdisim.ui.pages.detection",
    "/grafo": "fdisim.ui.pages.causal_model",
    "/resultados": "fdisim.ui.pages.results",
    "/comunicacion": "fdisim.ui.pages.communication",
}
IMPLEMENTED_PAGES = tuple(PAGES)
POLL_S = 0.25  # sondeo de detecciones: una alarma se ve en menos de 1 s (RNF-15)


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
    from fdisim.ui.pages import (
        causal_model,
        communication,
        detection,
        experiments,
        operation,
        results,
    )
    from fdisim.ui.run_manager import RunManager
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
    manager = RunManager(config, state, config_path, logger)
    tasks: list[asyncio.Task] = []

    async def poll_detections() -> None:
        while True:
            try:
                await asyncio.to_thread(manager.poll)
            except Exception as exc:  # una corrida que termina no debe tumbar la HMI
                logger.debug("Sondeo de detecciones: %s", exc)
            await asyncio.sleep(POLL_S)

    async def startup() -> None:
        await link.start()
        tasks.append(asyncio.create_task(poll_detections()))
        manager.prepare()

    async def shutdown() -> None:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if manager.owns_runs and manager.running:
            manager.stop()
        await link.stop()

    app.on_startup(startup)
    app.on_shutdown(shutdown)
    operation.register(state, link, config)
    experiments.register(state, link, manager)
    detection.register(state, link, manager, config)
    causal_model.register(state, link, config)
    results.register(state, link, manager)
    communication.register(state, link, manager, config)
    ui.run(
        host=host or str(ui_cfg.get("host", "127.0.0.1")),
        port=int(port or ui_cfg.get("port", 8080)),
        title="FDISim-OPCUA",
        reload=False,
        show=show,
        show_welcome_message=False,
        favicon="💧",
    )
