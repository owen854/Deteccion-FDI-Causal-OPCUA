"""Bitácora estructurada por componente y por corrida (RF-55).

Cada proceso (planta, gateway, controlador, monitor, HMI y orquestador) escribe en
``logs/<run_id>/<componente>.log`` con formato común, para correlacionar eventos por
identificador de corrida. Las advertencias y errores también se muestran en la consola.

Implementado en la Fase 3.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fdisim.common import paths

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(run_id)s | %(name)s | %(message)s"
_MARK = "_fdisim_handler"


class _RunIdFilter(logging.Filter):
    """Añade ``run_id`` a todos los registros que pasan por el manejador."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


def log_path(component: str, run_id: str, log_dir: str | Path | None = None) -> Path:
    return paths.resolve(log_dir or paths.LOGS_DIR) / run_id / f"{component}.log"


def configure_logging(
    component: str,
    run_id: str,
    level: str = "INFO",
    log_dir: str | Path | None = None,
    console_level: str = "WARNING",
) -> logging.Logger:
    """Configura y devuelve el logger del componente para la corrida ``run_id``.

    Es idempotente: reemplaza los manejadores instalados por una llamada anterior.
    """
    path = log_path(component, run_id, log_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT)
    run_filter = _RunIdFilter(run_id)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    console = logging.StreamHandler()
    console.setLevel(console_level.upper())
    for handler in (file_handler, console):
        handler.setFormatter(formatter)
        handler.addFilter(run_filter)
        setattr(handler, _MARK, True)
        root.addHandler(handler)

    numeric = logging.getLevelName(level.upper())
    root.setLevel(numeric)
    # asyncua es muy detallado en INFO; sus advertencias y errores sí se conservan.
    logging.getLogger("asyncua").setLevel(max(logging.WARNING, numeric))
    return logging.getLogger(f"fdisim.{component}")
