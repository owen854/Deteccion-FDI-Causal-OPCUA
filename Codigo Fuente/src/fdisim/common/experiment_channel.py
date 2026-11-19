"""Canal local HMI ↔ orquestador del plano de experimento (RF-23, RF-48).

La HMI corre en su propio subproceso y no comparte las colas de ``multiprocessing``. Para armar
o desarmar ataques en caliente habla con el orquestador por este canal, que luego reenvía la
orden al gateway por el plano de experimento. Los comandos del experimento nunca viajan por
OPC UA: el plano de datos queda exactamente como lo vería un sistema real.

- Transporte: ``multiprocessing.connection`` sobre 127.0.0.1 (RNF-11), con autenticación por
  clave aleatoria de 32 bytes por corrida (desafío HMAC).
- El orquestador publica la dirección y la clave a la HMI mediante variables de entorno.
- Mensajes: diccionarios ``{"cmd": "status" | "arm" | "disarm", ...}``; respuesta
  ``{"ok": bool, ...}``.

Implementado en la Fase 4.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from typing import Any

ENV_ADDRESS = "FDISIM_EXPERIMENT_ADDRESS"
ENV_KEY = "FDISIM_EXPERIMENT_KEY"

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class ExperimentServer:
    """Lado del orquestador: atiende a la HMI en un hilo propio."""

    def __init__(self, handler: Handler, host: str = "127.0.0.1") -> None:
        self.handler = handler
        self.authkey = secrets.token_bytes(32)
        self._listener = Listener((host, 0), authkey=self.authkey)
        self.address: tuple[str, int] = self._listener.address
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="canal-experimento", daemon=True)
        self.logger = logging.getLogger("fdisim.orchestrator.canal")

    def start(self) -> None:
        self._thread.start()

    def environment(self) -> dict[str, str]:
        """Variables de entorno para que un subproceso (la HMI) se conecte."""
        host, port = self.address
        return {ENV_ADDRESS: f"{host}:{port}", ENV_KEY: self.authkey.hex()}

    def close(self) -> None:
        self._closed.set()
        self._listener.close()

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                if self._closed.is_set():
                    return
                continue
            except Exception:  # autenticación fallida u otro error de un cliente
                self.logger.warning("Conexión rechazada en el canal de experimento")
                continue
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: Any) -> None:
        with conn:
            while not self._closed.is_set():
                try:
                    message = conn.recv()
                except (EOFError, OSError):
                    return
                try:
                    reply = self.handler(dict(message))
                except Exception as exc:
                    reply = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
                try:
                    conn.send(reply)
                except OSError:
                    return


class ExperimentClient:
    """Lado de la HMI: solicita estado y arma o desarma ataques."""

    def __init__(self, address: tuple[str, int], authkey: bytes) -> None:
        self.address = address
        self.authkey = authkey
        self._conn: Any = None
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> ExperimentClient | None:
        address, key = os.environ.get(ENV_ADDRESS), os.environ.get(ENV_KEY)
        if not address or not key:
            return None
        host, port = address.rsplit(":", 1)
        return cls((host, int(port)), bytes.fromhex(key))

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            try:
                if self._conn is None:
                    self._conn = Client(self.address, authkey=self.authkey)
                self._conn.send(message)
                return dict(self._conn.recv())
            except (OSError, EOFError, AuthenticationError) as exc:
                self._conn = None
                return {"ok": False, "error": f"Sin corrida activa ({exc.__class__.__name__})"}

    def status(self) -> dict[str, Any]:
        return self.request({"cmd": "status"})

    def arm(self, attack: dict[str, Any]) -> dict[str, Any]:
        return self.request({"cmd": "arm", "attack": attack})

    def disarm(self, attack_id: str) -> dict[str, Any]:
        return self.request({"cmd": "disarm", "attack_id": attack_id})
