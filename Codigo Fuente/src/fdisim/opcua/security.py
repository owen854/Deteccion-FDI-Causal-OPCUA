"""Configuración de seguridad OPC UA (RF-12, RNF-09, RNF-10; Informe OE1 §3.5).

Política por defecto: SignAndEncrypt + Basic256Sha256 (o Aes256_Sha256_RsaPss).
Las políticas obsoletas se rechazan; el modo None solo se admite con
``allow_insecure_debug=True``.

Fase de implementación: Fases 1 (prueba de concepto) y 3. Dependencias: asyncua, cryptography.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class SecurityMode(StrEnum):
    NONE = "None"
    SIGN = "Sign"
    SIGN_AND_ENCRYPT = "SignAndEncrypt"


class UserAuth(StrEnum):
    ANONYMOUS = "anonymous"
    USERNAME = "username"
    CERTIFICATE = "certificate"


ALLOWED_POLICIES: frozenset[str] = frozenset(
    {"Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss"}
)
DEPRECATED_POLICIES: frozenset[str] = frozenset({"Basic128Rsa15", "Basic256"})


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    mode: SecurityMode = SecurityMode.SIGN_AND_ENCRYPT
    policy: str = "Basic256Sha256"
    user_auth: UserAuth = UserAuth.USERNAME
    certs_dir: Path = Path("certs")
    allow_insecure_debug: bool = False

    def check(self) -> None:
        """Aplica RNF-09: rechaza políticas obsoletas y el modo None sin bandera de depuración."""
        if self.policy in DEPRECATED_POLICIES:
            raise ValueError(f"Política obsoleta no permitida: {self.policy}")
        if self.mode is SecurityMode.NONE:
            if not self.allow_insecure_debug:
                raise ValueError(
                    "El modo None requiere allow_insecure_debug=True (solo depuración)"
                )
        elif self.policy not in ALLOWED_POLICIES:
            raise ValueError(f"Política no soportada: {self.policy}")


async def apply_server_security(server: Any, config: SecurityConfig, component: str) -> None:
    """Configura en un servidor asyncua: políticas, certificado, usuarios y trust list."""
    raise NotImplementedError("Fase 3 — RF-12: seguridad del servidor")


async def apply_client_security(client: Any, config: SecurityConfig, component: str) -> None:
    """Configura en un cliente asyncua: política, modo, certificado y credenciales."""
    raise NotImplementedError("Fase 3 — RF-12: seguridad del cliente")
