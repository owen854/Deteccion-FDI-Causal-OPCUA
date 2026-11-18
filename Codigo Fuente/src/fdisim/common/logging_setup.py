"""Bitácora estructurada por componente y por corrida (RF-55).

Cada proceso (planta, gateway, controlador, monitor, HMI) escribe en
``logs/<run_id>/<componente>.log`` con formato común, para correlacionar eventos por
identificador de corrida.

Fase de implementación: Fase 3.
"""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(run_id)s | %(name)s | %(message)s"


def configure_logging(component: str, run_id: str, level: str = "INFO") -> logging.Logger:
    """Configura y devuelve el logger del componente para la corrida ``run_id``."""
    raise NotImplementedError("Fase 3 — RF-55: bitácora por componente")
