"""Pruebas unitarias de la configuración de seguridad y de la PKI (RF-12, RNF-09, RNF-10)."""

from __future__ import annotations

import pytest

from fdisim.common import paths
from fdisim.opcua.information_model import unece_unit_id
from fdisim.opcua.security import (
    PasswordUserManager,
    SecurityConfig,
    SecurityMode,
    application_uri,
    create_credentials,
    load_credentials,
)


def test_configuracion_por_defecto_del_proyecto_es_segura():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    security = SecurityConfig.from_config(cfg["opcua"]["security"])
    assert security.mode is SecurityMode.SIGN_AND_ENCRYPT
    assert security.policy == "Basic256Sha256"


@pytest.mark.parametrize("policy", ["Basic128Rsa15", "Basic256"])
def test_politicas_obsoletas_rechazadas(policy):
    with pytest.raises(ValueError):
        SecurityConfig.from_config({"policy": policy})


def test_unidades_unece():
    assert unece_unit_id("CMT") == 0x434D54  # centímetro
    assert unece_unit_id("P1") == 0x5031  # porcentaje


def test_uri_de_aplicacion():
    assert application_uri("gateway") == "urn:unipamplona:siddfai:fdisim:gateway"


def test_credenciales_y_gestor_de_usuarios(tmp_path):
    create_credentials(tmp_path, users=("gateway", "monitor"))
    creds = load_credentials(tmp_path)
    assert set(creds) == {"gateway", "monitor"} and all(len(p) >= 20 for p in creds.values())
    create_credentials(tmp_path, users=("gateway", "hmi"))  # conserva las existentes
    assert load_credentials(tmp_path)["gateway"] == creds["gateway"]

    manager = PasswordUserManager(creds)
    assert manager.get_user(None, "gateway", creds["gateway"]) is not None
    assert manager.get_user(None, "gateway", creds["gateway"].encode()) is not None
    assert manager.get_user(None, "gateway", "otra") is None
    assert manager.get_user(None, "desconocido", "x") is None
    assert manager.get_user(None, None, None) is None
