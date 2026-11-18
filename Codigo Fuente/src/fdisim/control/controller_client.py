"""Soft-PLC: controlador PID como cliente OPC UA independiente (RF-08).

Se conecta al **gateway** (no a la planta), se suscribe a LT-102 y a LIC-102.SP, ejecuta el PID
cada ``ts_s`` y escribe P-101. Como recibe los datos por el mismo canal que el monitor, un
ataque FDI en el gateway afecta realmente al lazo cerrado y al proceso físico.

Fase de implementación: Fase 3. Dependencia prevista: asyncua.
"""

from __future__ import annotations

from fdisim.control.pid import PIDController


class ControllerClient:
    def __init__(
        self, endpoint: str, pid: PIDController, controlled_tag: str, manipulated_tag: str
    ) -> None:
        self.endpoint = endpoint
        self.pid = pid
        self.controlled_tag = controlled_tag
        self.manipulated_tag = manipulated_tag

    async def run(self) -> None:
        """Bucle de control: suscripción → PID → escritura, hasta recibir STOP."""
        raise NotImplementedError("Fase 3 — RF-08: lazo cerrado a través de OPC UA")

    async def stop(self) -> None:
        raise NotImplementedError("Fase 3 — RF-08")
