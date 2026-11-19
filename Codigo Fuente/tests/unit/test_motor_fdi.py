"""Motor de inyección FDI: sigilo, programador, inyector y etiquetas (RF-16, RF-20 a RF-24)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from fdisim.attacks.injector import FdiInjector
from fdisim.attacks.scheduler import AttackScheduler
from fdisim.attacks.stealth import StealthFilter
from fdisim.common.bus import EventType, ExperimentHub
from fdisim.common.types import LT_101, LT_102, P_101, AttackSpec, AttackType, StealthSpec
from fdisim.data.labels import (
    events_frame,
    events_from_frame,
    label_ground_truth,
    label_times,
    merge_events,
)

STEALTH = StealthSpec(enabled=True, envelope=(2.0, 45.0), max_rate_per_s=0.5)


def spec(
    kind=AttackType.BIAS,
    targets=(LT_102,),
    start=10.0,
    duration=20.0,
    stealth=None,
    aid="A1",
    **params,
):
    return AttackSpec(
        aid,
        kind,
        tuple(targets),
        start,
        duration,
        params or {"bias": 2.0},
        stealth or StealthSpec(enabled=False),
    )


def run(injector: FdiInjector, tag: str, signal, t0=0.0, t1=40.0, dt=0.1):
    times = np.round(np.arange(t0 + dt, t1 + 1e-9, dt), 6)
    return times, np.array([injector.process(tag, signal(t), t) for t in times])


def test_sigilo_limita_la_desviacion_y_conserva_el_ruido():
    rng = np.random.default_rng(0)
    noise = {round(t, 6): rng.normal(0, 0.1) for t in np.arange(0.1, 40.05, 0.1)}
    injector = FdiInjector(AttackScheduler([spec(stealth=STEALTH)]))
    times, out = run(injector, LT_102, lambda t: 25.0 + noise[round(t, 6)])
    legit = np.array([25.0 + noise[t] for t in times])
    delta = out - legit
    assert np.all(delta[times < 10.0] == 0)  # transparente antes de la ventana
    assert np.max(np.abs(np.diff(delta))) <= 0.5 * 0.1 + 1e-9  # tasa de la desviación limitada
    assert delta[(times >= 15) & (times < 25)] == pytest.approx(2.0)  # sesgo completo
    assert abs(delta[np.searchsorted(times, 30.0) - 1]) <= 0.05 + 1e-9  # sale gradualmente
    assert np.all(delta[times >= 30.0] == 0)
    inside = (times >= 15) & (times < 25)
    assert np.std(np.diff(out[inside])) == pytest.approx(np.std(np.diff(legit[inside])))


def test_envolvente_de_sigilo():
    filt = StealthFilter(StealthSpec(enabled=True, envelope=(2.0, 45.0)))
    assert filt.apply(LT_102, 47.0, 1.0) == 45.0 and filt.apply(LT_102, -1.0, 1.0) == 2.0
    assert StealthFilter(StealthSpec(enabled=False)).apply(LT_102, 99.0, 1.0) == 99.0


def test_programador_etiquetas_eventos_y_desarme():
    scheduler = AttackScheduler([spec()])
    with pytest.raises(ValueError):
        scheduler.arm(spec())  # id repetido
    assert scheduler.label_at(9.9) == 0 and scheduler.label_at(10.0) == 1
    assert [e.t_end for e in scheduler.transitions(12.0)] == [None]  # inicio, una sola vez
    assert scheduler.transitions(13.0) == []
    scheduler.disarm("A1", 15.0)
    assert scheduler.label_at(15.0) == 0 and scheduler.active_for(LT_102, 14.9)
    assert [e.t_end for e in scheduler.transitions(15.0)] == [15.0]
    assert scheduler.events()[0].t_end == 15.0


def test_inyector_coordinado_y_eventos_por_el_plano_de_experimento():
    hub = ExperimentHub(["gateway"], multiprocess=False)
    attacks = [spec(aid="A1", bias=2.0), spec(targets=(LT_101,), aid="A2", bias=1.0)]
    injector = FdiInjector(AttackScheduler(attacks), hub.bus_for("gateway"))
    assert injector.process(LT_102, 25.0, 12.0) == 27.0
    assert injector.process(LT_101, 16.0, 12.0) == 17.0
    assert injector.process(LT_102, 25.0, 31.0) == 25.0
    events = [e.payload for e in hub.drain(0.1) if e.type is EventType.ATTACK]
    assert {(e.attack_id, e.t_end) for e in events} == {
        ("A1", None),
        ("A2", None),
        ("A1", 30.0),
        ("A2", 30.0),
    }


def test_replay_armado_en_caliente_usa_el_historial():
    injector = FdiInjector(AttackScheduler())
    for k in range(1, 101):  # 10 s de y(t) = t
        injector.process(LT_102, k / 10, k / 10)
    armed = injector.arm(
        spec(AttackType.REPLAY, start=0.0, duration=30.0, record_s=5.0), start_now=True
    )
    assert armed.start_s == 10.0
    assert injector.process(LT_102, 99.0, 10.1) == pytest.approx(5.1)
    assert injector.process(LT_102, 99.0, 15.1) == pytest.approx(5.1)  # bucle de 5 s


def test_ataque_al_actuador_altera_la_orden():
    injector = FdiInjector(AttackScheduler([spec(targets=(P_101,), bias=8.0)]))
    assert injector.process_command(P_101, 50.0, 5.0) == 50.0
    assert injector.process_command(P_101, 50.0, 12.0) == 58.0
    assert injector.is_attacking(P_101, 12.0) and not injector.is_attacking(LT_102, 12.0)


def test_etiquetas_y_tabla_de_ataques():
    events = merge_events([_event("A1", None), _event("A1", 15.0)])  # inicio y fin
    assert len(events) == 1 and events[0].t_end == 15.0
    label, attack_id, attacked = label_times(
        [9.9, 10.0, 14.9, 15.0], events, [LT_102, LT_102, LT_101, LT_102]
    )
    assert label.tolist() == [0, 1, 1, 0]
    assert attack_id.tolist() == [None, "A1", "A1", None]
    assert attacked.tolist() == [0, 1, 0, 0]
    frame = events_frame(events)
    assert events_from_frame(frame) == events
    import pandas as pd

    gt = label_ground_truth(pd.DataFrame({"sim_time": [9.0, 12.0]}), events)
    assert gt["attack_active"].tolist() == [False, True]


def _event(aid, end):
    from fdisim.common.types import AttackEvent

    return AttackEvent(aid, AttackType.BIAS, (LT_102,), 10.0, end, {"bias": 2.0})


def test_parametros_obligatorios_de_cada_ataque():
    from fdisim.attacks import create_attack

    with pytest.raises(ValueError, match="bias"):
        create_attack(AttackSpec("A", AttackType.BIAS, (LT_102,), 0, 1))
    with pytest.raises(ValueError, match="slope_per_s"):
        create_attack(AttackSpec("A", AttackType.RAMP, (LT_102,), 0, 1))
    with pytest.raises(ValueError, match="record_s"):
        create_attack(AttackSpec("A", AttackType.REPLAY, (LT_102,), 0, 1))
    ramp = create_attack(
        AttackSpec(
            "A", AttackType.RAMP, (LT_102,), 0, 100, {"slope_per_s": -0.1, "max_deviation": 2.0}
        )
    )
    assert ramp.falsify(LT_102, 25.0, 50.0) == 23.0  # pendiente negativa, limitada
    assert not math.isnan(ramp.deviation(1.0))
