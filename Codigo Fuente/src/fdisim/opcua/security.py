"""Seguridad OPC UA: certificados, listas de confianza, usuarios y políticas.

Requerimientos: RF-12, RNF-09, RNF-10.

Política por defecto: SignAndEncrypt + Basic256Sha256 (o Aes256_Sha256_RsaPss). Las políticas
obsoletas se rechazan; el modo None solo se admite con ``allow_insecure_debug=True``.

Infraestructura de clave pública (PKI) local, nunca versionada (ver ``.gitignore``)::

    certs/
    ├── <componente>/cert.der        certificado X.509 de aplicación (autofirmado)
    ├── <componente>/key.pem         clave privada RSA 2048
    ├── <componente>/trusted/*.der   certificados de los pares en los que confía
    └── credenciales.json            usuarios y contraseñas de prueba de los clientes

Cada componente solo confía en los pares con los que habla (``TRUST``):
controller, monitor, hmi → gateway → plant_server.

Implementado en la Fase 1 (prueba de concepto) y reutilizado desde la Fase 3.
Dependencias: asyncua, cryptography (importadas de forma diferida).
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import shutil
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from fdisim.common import paths


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

APP_URI_PREFIX = "urn:unipamplona:siddfai:fdisim"
COMPONENTS: tuple[str, ...] = ("plant_server", "gateway", "controller", "monitor", "hmi")
SERVER_COMPONENTS: frozenset[str] = frozenset({"plant_server", "gateway"})
TRUST: Mapping[str, tuple[str, ...]] = {
    "plant_server": ("gateway",),
    "gateway": ("plant_server", "controller", "monitor", "hmi"),
    "controller": ("gateway",),
    "monitor": ("gateway",),
    "hmi": ("gateway",),
}
CLIENT_USERS: tuple[str, ...] = ("gateway", "controller", "monitor", "hmi", "uaexpert")
# Usuarios que acepta cada servidor (mínimo privilegio): la planta solo atiende al gateway y el
# gateway a sus clientes; ``uaexpert`` queda habilitado para las pruebas de interoperabilidad.
SERVER_USERS: Mapping[str, tuple[str, ...]] = {
    "plant_server": ("gateway", "uaexpert"),
    "gateway": ("controller", "monitor", "hmi", "uaexpert"),
}
CREDENTIALS_FILE = "credenciales.json"
SUBJECT = {
    "organizationName": "Universidad de Pamplona",
    "organizationalUnitName": "Semillero SIDDFAI",
    "countryName": "CO",
}

# Nombre de la política en la configuración → (nombre en asyncua, clase de política del cliente)
_POLICIES: Mapping[str, tuple[str, str]] = {
    "Basic256Sha256": ("Basic256Sha256", "SecurityPolicyBasic256Sha256"),
    "Aes128_Sha256_RsaOaep": ("Aes128Sha256RsaOaep", "SecurityPolicyAes128Sha256RsaOaep"),
    "Aes256_Sha256_RsaPss": ("Aes256Sha256RsaPss", "SecurityPolicyAes256Sha256RsaPss"),
}


def application_uri(component: str) -> str:
    """URI de aplicación; debe coincidir con el SubjectAltName del certificado."""
    return f"{APP_URI_PREFIX}:{component}"


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

    @classmethod
    def from_config(cls, security: Mapping[str, Any]) -> SecurityConfig:
        """Construye la configuración desde la sección ``opcua.security`` del YAML."""
        cfg = cls(
            mode=SecurityMode(security.get("mode", "SignAndEncrypt")),
            policy=str(security.get("policy", "Basic256Sha256")),
            user_auth=UserAuth(security.get("user_auth", "username")),
            certs_dir=Path(security.get("certs_dir", "certs")),
            allow_insecure_debug=bool(security.get("allow_insecure_debug", False)),
        )
        cfg.check()
        return cfg


# ---------------------------------------------------------------------------
# PKI: certificados, listas de confianza y credenciales
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ComponentPki:
    component: str
    cert: Path
    key: Path
    trusted_dir: Path

    def exists(self) -> bool:
        return self.cert.is_file() and self.key.is_file()


def pki_paths(component: str, certs_dir: str | Path) -> ComponentPki:
    base = paths.resolve(certs_dir) / component
    return ComponentPki(component, base / "cert.der", base / "key.pem", base / "trusted")


def generate_application_certificate(
    component: str, certs_dir: str | Path, days: int = 365, hostnames: list[str] | None = None
) -> ComponentPki:
    """Genera clave RSA 2048 y certificado de aplicación conforme a OPC 10000-4/6 (vía asyncua).

    SubjectAltName: URI de aplicación, nombre del equipo, ``localhost`` y 127.0.0.1.
    Uso extendido: clientAuth para todos; serverAuth para servidores.
    """
    from asyncua.crypto import cert_gen
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import ExtendedKeyUsageOID

    pki = pki_paths(component, certs_dir)
    pki.trusted_dir.mkdir(parents=True, exist_ok=True)
    hosts = list(dict.fromkeys(hostnames or [socket.gethostname(), "localhost"]))
    san: list[x509.GeneralName] = [x509.UniformResourceIdentifier(application_uri(component))]
    san += [x509.DNSName(h) for h in hosts]
    san.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    uses = [ExtendedKeyUsageOID.CLIENT_AUTH]
    if component in SERVER_COMPONENTS:
        uses.append(ExtendedKeyUsageOID.SERVER_AUTH)

    key = cert_gen.generate_private_key()
    cert = cert_gen.generate_self_signed_app_certificate(
        key, application_uri(component), dict(SUBJECT), san, extended=uses, days=days
    )
    pki.key.write_bytes(cert_gen.dump_private_key_as_pem(key))
    pki.cert.write_bytes(cert.public_bytes(Encoding.DER))
    return pki


def build_trust_lists(
    certs_dir: str | Path, trust: Mapping[str, tuple[str, ...]] = TRUST
) -> dict[str, list[str]]:
    """Copia el certificado de cada par en la carpeta ``trusted`` de quien confía en él."""
    result: dict[str, list[str]] = {}
    for component, peers in trust.items():
        target = pki_paths(component, certs_dir).trusted_dir
        target.mkdir(parents=True, exist_ok=True)
        result[component] = []
        for peer in peers:
            peer_cert = pki_paths(peer, certs_dir).cert
            if peer_cert.is_file():
                shutil.copyfile(peer_cert, target / f"{peer}.der")
                result[component].append(peer)
    return result


def create_credentials(
    certs_dir: str | Path, users: tuple[str, ...] = CLIENT_USERS, overwrite: bool = False
) -> Path:
    """Crea ``credenciales.json`` con contraseñas aleatorias de prueba (solo laboratorio)."""
    path = paths.resolve(certs_dir) / CREDENTIALS_FILE
    current: dict[str, str] = {}
    if path.is_file() and not overwrite:
        current = load_credentials(certs_dir)
    for user in users:
        current.setdefault(user, secrets.token_urlsafe(18))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"usuarios": current}, indent=2), encoding="utf-8")
    return path


def setup_pki(certs_dir: str | Path, days: int = 365, force: bool = False) -> dict[str, Any]:
    """Crea lo que falte de la PKI local: certificados, listas de confianza y credenciales.

    Devuelve un resumen con los componentes creados y las listas de confianza resultantes.
    """
    created = []
    for component in COMPONENTS:
        if pki_paths(component, certs_dir).exists() and not force:
            continue
        generate_application_certificate(component, certs_dir, days=days)
        created.append(component)
    trust = build_trust_lists(certs_dir)
    credentials = create_credentials(certs_dir)
    return {"created": created, "trust": trust, "credentials": credentials}


def find_uaexpert_certificate() -> Path | None:
    """Certificado de aplicación de UaExpert en el perfil del usuario (Windows)."""
    import os

    appdata = Path(os.environ.get("APPDATA", ""))
    candidates = sorted(appdata.glob("unifiedautomation/uaexpert/PKI/own/certs/*.der"))
    return candidates[-1] if candidates else None


def trust_certificate(
    cert: str | Path, certs_dir: str | Path, components: tuple[str, ...], name: str
) -> list[Path]:
    """Agrega un certificado externo (p. ej. UaExpert) a la lista de confianza de servidores."""
    copied = []
    for component in components:
        target = pki_paths(component, certs_dir).trusted_dir / f"{name}.der"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cert, target)
        copied.append(target)
    return copied


def load_credentials(certs_dir: str | Path) -> dict[str, str]:
    path = paths.resolve(certs_dir) / CREDENTIALS_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe {path}. Ejecute: python scripts/generar_certificados.py"
        )
    return dict(json.loads(path.read_text(encoding="utf-8"))["usuarios"])


class PasswordUserManager:
    """Gestor de usuarios de asyncua basado en ``credenciales.json``.

    Compara las contraseñas en tiempo constante.
    """

    def __init__(
        self, credentials: Mapping[str, str], allowed: tuple[str, ...] | None = None
    ) -> None:
        self._credentials = {
            user: pwd for user, pwd in credentials.items() if allowed is None or user in allowed
        }

    def get_user(
        self,
        iserver: Any,
        username: str | None = None,
        password: Any = None,
        certificate: Any = None,
    ) -> Any:
        from asyncua.crypto.permission_rules import User, UserRole

        if username is None or password is None:
            return None
        if isinstance(password, bytes):
            password = password.decode("utf-8", errors="ignore")
        expected = self._credentials.get(username)
        if expected is None or not hmac.compare_digest(expected.encode(), str(password).encode()):
            return None
        return User(role=UserRole.User, name=username)


# ---------------------------------------------------------------------------
# Aplicación de la seguridad a servidores y clientes asyncua
# ---------------------------------------------------------------------------
def server_policy_type(config: SecurityConfig) -> Any:
    from asyncua import ua

    if config.mode is SecurityMode.NONE:
        return ua.SecurityPolicyType.NoSecurity
    suffix = "SignAndEncrypt" if config.mode is SecurityMode.SIGN_AND_ENCRYPT else "Sign"
    return getattr(ua.SecurityPolicyType, f"{_POLICIES[config.policy][0]}_{suffix}")


def client_policy_class(config: SecurityConfig) -> Any:
    from asyncua.crypto import security_policies

    return getattr(security_policies, _POLICIES[config.policy][1])


async def apply_server_security(server: Any, config: SecurityConfig, component: str) -> None:
    """Configura en un servidor asyncua (antes de ``start``): endpoint seguro, certificado,
    validación de clientes contra su lista de confianza e identidad de usuario."""
    from asyncua import ua
    from asyncua.crypto.truststore import TrustStore
    from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
    from asyncua.server.user_managers import CertificateUserManager, PermissiveUserManager

    config.check()
    server.set_security_policy([server_policy_type(config)])

    if config.mode is not SecurityMode.NONE:
        pki = pki_paths(component, config.certs_dir)
        if not pki.exists():
            raise FileNotFoundError(
                f"Faltan los certificados de '{component}'. "
                "Ejecute: python scripts/generar_certificados.py"
            )
        await server.load_certificate(str(pki.cert))
        await server.load_private_key(str(pki.key))
        trust_store = TrustStore([pki.trusted_dir], [])
        await trust_store.load()
        options = (
            CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT
        )
        server.set_certificate_validator(CertificateValidator(options, trust_store))

    if config.user_auth is UserAuth.USERNAME:
        server.set_identity_tokens([ua.UserNameIdentityToken])
        server.iserver.user_manager = PasswordUserManager(
            load_credentials(config.certs_dir), SERVER_USERS.get(component)
        )
    elif config.user_auth is UserAuth.CERTIFICATE:
        server.set_identity_tokens([ua.X509IdentityToken])
        manager = CertificateUserManager()
        for cert in sorted(pki_paths(component, config.certs_dir).trusted_dir.glob("*.der")):
            await manager.add_user(cert, name=cert.stem)
        server.iserver.user_manager = manager
    else:
        server.set_identity_tokens([ua.AnonymousIdentityToken])
        server.iserver.user_manager = PermissiveUserManager()


async def apply_client_security(
    client: Any, config: SecurityConfig, component: str, server_component: str
) -> None:
    """Configura en un cliente asyncua: URI de aplicación, política, modo, certificado propio,
    certificado del servidor (fijado desde la lista de confianza) y credenciales."""
    from asyncua import ua
    from asyncua.crypto.truststore import TrustStore
    from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions

    config.check()
    client.application_uri = application_uri(component)
    if config.mode is not SecurityMode.NONE:
        pki = pki_paths(component, config.certs_dir)
        server_cert = pki.trusted_dir / f"{server_component}.der"
        if not pki.exists() or not server_cert.is_file():
            raise FileNotFoundError(
                f"Faltan certificados de '{component}' o no confía en '{server_component}'. "
                "Ejecute: python scripts/generar_certificados.py"
            )
        await client.set_security(
            client_policy_class(config),
            certificate=str(pki.cert),
            private_key=str(pki.key),
            server_certificate=str(server_cert),
            mode=getattr(ua.MessageSecurityMode, config.mode.value),
        )
        trust_store = TrustStore([pki.trusted_dir], [])
        await trust_store.load()
        options = (
            CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_SERVER
        )
        client.certificate_validator = CertificateValidator(options, trust_store)

    if config.user_auth is UserAuth.USERNAME:
        client.set_user(component)
        client.set_password(load_credentials(config.certs_dir)[component])
