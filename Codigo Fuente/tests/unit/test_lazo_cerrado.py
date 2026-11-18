"""Criterios de aceptación de RF-07 y RF-09 en lazo cerrado offline, y carga de escenarios."""

from __future__ import annotations

import pytest

from fdisim.common import paths
from fdisim.common.config import ConfigError, load_scenario, load_yaml
from fdisim.common.types import LT_102, AttackType
from fdisim.control.performance import step_metrics
from fdisim.control.setpoint import SetpointProfile
from fdisim.orchestration.offline import prepare_closed_loop, run_closed_loop


@pytest.fixture(scope="module")
def config():
    return load_yaml(paths.DEFAULT_CONFIG)


def test_rf07_respuesta_al_escalon_en_operacion_nominal(config):
    scenario = load_scenario(paths.SCENARIOS_DIR / "escalon_consigna.yaml")
    loop = prepare_closed_loop(config, scenario, integrator="rk4")
    result = run_closed_loop(loop, scenario.duration_s)
    m = step_metrics(result.t, result.true[LT_102], 100.0, 30.0)
    assert m.steady_state_error_pct < 2.0
    assert m.overshoot_pct < 20.0
    assert m.settling_time_s is not None


def test_lazo_rechaza_ts_que_no_es_multiplo_de_dt(config):
    scenario = load_scenario(paths.SCENARIOS_DIR / "escalon_consigna.yaml")
    loop = prepare_closed_loop(config, scenario, control_overrides={"ts_s": 0.25})
    with pytest.raises(ValueError):
        run_closed_loop(loop, 10.0)


def test_transformacion_de_la_medicion_afecta_al_lazo(config):
    """El gancho que usará el inyector FDI en la Fase 4: un sesgo en lo que ve el PID desplaza
    el nivel real en sentido contrario."""
    scenario = load_scenario(paths.SCENARIOS_DIR / "escalon_consigna.yaml")
    loop = prepare_closed_loop(config, scenario, integrator="rk4")
    biased = run_closed_loop(loop, 1500.0, lambda t, tag, y: y + 2.0 if t >= 200 else y)
    assert biased.true[LT_102][-1] == pytest.approx(28.0, abs=0.3)


def test_perfil_de_consigna():
    profile = SetpointProfile([(100.0, 30.0), (0.0, 25.0)])
    assert [profile.value_at(t) for t in (-5, 0, 99.9, 100, 500)] == [25, 25, 25, 30, 30]
    assert profile.change_times() == [100.0]
    profile.override(27.0)
    assert profile.value_at(0.0) == 27.0
    profile.override(None)
    assert profile.value_at(0.0) == 25.0
    with pytest.raises(ConfigError):
        SetpointProfile.from_config([{"t_s": 0}])


def test_escenarios_heredan_de_la_base():
    normal = load_scenario(paths.SCENARIOS_DIR / "normal.yaml")
    sesgo = load_scenario(paths.SCENARIOS_DIR / "sesgo_lt102.yaml")
    assert sesgo.setpoint_profile == normal.setpoint_profile
    assert sesgo.disturbances == normal.disturbances
    assert sesgo.seed == 11 and sesgo.attacks[0].type is AttackType.BIAS
    assert sesgo.attacks[0].params["bias"] == 2.0 and sesgo.attacks[0].stealth.envelope == (
        2.0,
        45.0,
    )
    replay = load_scenario(paths.SCENARIOS_DIR / "replay_lt102.yaml")
    assert replay.setpoint_profile != normal.setpoint_profile  # lo redefine


def test_escenario_invalido(tmp_path):
    bad = tmp_path / "malo.yaml"
    bad.write_text(
        "name: x\nduration_s: 10\nsetpoint_profile: [{t_s: 0, value_cm: 25}]\n"
        "attacks: [{type: bias, targets: [XX-999], start_s: 1, duration_s: 1}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="targets"):
        load_scenario(bad)
