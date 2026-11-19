"""Prueba de humo de la arquitectura (criterio de salida de la Fase 0).

Verifica que todos los módulos se importan, que los registros de ataques y detectores están
completos, que el modelo de información y el grafo físico son coherentes, que existen los
archivos de configuración y que la CLI se construye.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import fdisim
from fdisim.attacks import registered_attacks
from fdisim.causal.prior_graph import PHYSICAL_LINKS, parents
from fdisim.cli import build_parser, main
from fdisim.common import paths
from fdisim.common.types import LT_101, LT_102, PROCESS_TAGS, AttackSpec, AttackType, DetectorKind
from fdisim.detection import registered_detectors
from fdisim.detection.isolation import SIGNATURES
from fdisim.opcua.information_model import PLANT_VARIABLES, variable_by_tag
from fdisim.opcua.security import SecurityConfig, SecurityMode

SUBPACKAGES = {
    "common",
    "process",
    "control",
    "opcua",
    "attacks",
    "data",
    "causal",
    "detection",
    "evaluation",
    "orchestration",
    "ui",
}


def all_modules() -> list[str]:
    names = [m.name for m in pkgutil.walk_packages(fdisim.__path__, prefix="fdisim.")]
    return [n for n in names if not n.endswith("__main__")]  # __main__ ejecuta la CLI


def test_subpaquetes_de_la_arquitectura_presentes():
    top = {name.split(".")[1] for name in all_modules()}
    assert top >= SUBPACKAGES


@pytest.mark.parametrize("module", all_modules())
def test_todos_los_modulos_se_importan(module):
    importlib.import_module(module)


def test_registros_de_ataques_y_detectores():
    assert set(registered_attacks()) == {AttackType.BIAS, AttackType.RAMP, AttackType.REPLAY}
    assert set(registered_detectors()) == {DetectorKind.CAUSAL, DetectorKind.THRESHOLD}


def test_modelo_de_informacion_coherente():
    tags = [v.tag for v in PLANT_VARIABLES]
    assert len(tags) == len(set(tags)), "etiquetas duplicadas"
    for tag in PROCESS_TAGS:
        assert variable_by_tag(tag).eu_range is not None
    writable = {v.tag for v in PLANT_VARIABLES if v.writable}
    assert writable == {"P-101", "LIC-102.SP"}


def test_grafo_fisico_usa_etiquetas_conocidas():
    for link in PHYSICAL_LINKS:
        assert link.source in PROCESS_TAGS and link.target in PROCESS_TAGS
        assert link.lag in (0, 1)
    assert {lk.source for lk in parents(LT_102)} == {LT_101, LT_102}


def test_firmas_de_identificacion_sobre_variables_del_grafo():
    for tag, signature in SIGNATURES.items():
        assert tag in signature
        assert signature <= set(PROCESS_TAGS)


def test_ventana_de_ataque():
    spec = AttackSpec("A1", AttackType.BIAS, (LT_102,), start_s=10.0, duration_s=5.0)
    assert not spec.is_active(9.9) and spec.is_active(10.0) and not spec.is_active(15.0)


def test_seguridad_rechaza_configuraciones_inseguras():
    SecurityConfig().check()  # por defecto: SignAndEncrypt + Basic256Sha256
    with pytest.raises(ValueError):
        SecurityConfig(policy="Basic128Rsa15").check()
    with pytest.raises(ValueError):
        SecurityConfig(mode=SecurityMode.NONE).check()
    SecurityConfig(mode=SecurityMode.NONE, allow_insecure_debug=True).check()


def test_archivos_de_configuracion_presentes():
    assert paths.DEFAULT_CONFIG.is_file()
    expected = {"normal.yaml", "sesgo_lt102.yaml", "rampa_lt102.yaml", "replay_lt102.yaml"}
    assert expected <= {p.name for p in paths.SCENARIOS_DIR.glob("*.yaml")}
    assert (paths.CAMPAIGNS_DIR / "campana_oe4.yaml").is_file()


def test_configuracion_yaml_valida():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    assert {"simulation", "plant", "control", "opcua", "detection", "data", "ui"} <= set(cfg)
    assert cfg["opcua"]["security"]["mode"] == "SignAndEncrypt"
    for scenario in paths.SCENARIOS_DIR.glob("*.yaml"):
        data = yaml.safe_load(scenario.read_text(encoding="utf-8"))
        for attack in data.get("attacks", []):
            assert attack["type"] in {t.value for t in AttackType}
            assert set(attack["targets"]) <= set(PROCESS_TAGS)


def test_cli_construye_y_reporta_pendientes(capsys):
    parser = build_parser()
    for command in ("run", "train", "detect", "campaign", "report", "ui", "certs"):
        assert command in parser._subparsers._group_actions[0].choices  # noqa: SLF001
    assert main(["detect", "--run", "x"]) == 2
    assert "Fase 6" in capsys.readouterr().err
