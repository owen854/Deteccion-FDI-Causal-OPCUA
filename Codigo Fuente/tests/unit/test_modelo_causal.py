"""Modelo causal: grafo, descubrimiento, comparación, SCM y persistencia (RF-28 a RF-32)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from fdisim.causal.discovery import DiscoveredLink, run_granger, run_pcmci
from fdisim.causal.graph_compare import (
    GRID_DECISIONS,
    compare,
    consolidate,
    edge_precision_recall,
    structural_hamming_distance,
)
from fdisim.causal.model_store import load_model, save_model
from fdisim.causal.prior_graph import (
    PHYSICAL_LINKS,
    build_prior_graph,
    edge_set,
    export_graph,
    links_from_graph,
    load_graph,
)
from fdisim.causal.scm import PhysicsInformedSCM, RegressionSCM, model_from_dict
from fdisim.common.config import load_config, load_scenario
from fdisim.common.paths import SCENARIOS_DIR
from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102
from fdisim.data.dataset import align_samples
from fdisim.orchestration.offline import simulate_offline


@pytest.fixture(scope="module")
def config():
    return load_config().to_dict()


@pytest.fixture(scope="module")
def grid(config):
    """Dos corridas normales offline de 700 s en la rejilla de 0,5 s (con cambio de consigna)."""
    scenario = load_scenario(SCENARIOS_DIR / "normal.yaml")
    frames = []
    for seed in (101, 102):
        result = simulate_offline(config, scenario, seed=seed, duration_s=700.0)
        frames.append(align_samples(result.samples, 0.5).assign(run_id=f"r{seed}"))
    return pd.concat(frames, ignore_index=True)


def test_grafo_fisico_se_exporta_y_recarga(tmp_path):
    graph = build_prior_graph()
    assert graph.number_of_edges() == len(PHYSICAL_LINKS)
    for fmt in ("graphml", "json"):
        path = export_graph(graph, tmp_path / f"g.{fmt}", fmt)
        assert edge_set(links_from_graph(load_graph(path))) == edge_set(PHYSICAL_LINKS)


def test_metricas_de_comparacion():
    ref = {("A", "B", 1), ("B", "C", 0), ("C", "C", 1)}
    est = {("A", "B", 1), ("C", "B", 0), ("A", "C", 2), ("X", SP_102, 1)}
    assert structural_hamming_distance(ref, est) == 3  # invertido (1) + faltante + extra
    precision, recall = edge_precision_recall(ref, est)
    assert precision == pytest.approx(1 / 3) and recall == pytest.approx(1 / 3)
    metrics = compare(ref, ref)
    assert metrics["shd"] == 0 and metrics["precision"] == metrics["recall"] == 1.0


def test_consolidacion_justifica_cada_cambio():
    found = {
        "PCMCI+": [
            DiscoveredLink(P_101, FT_101, 1, 0.0, 0.7, "pcmci+"),
            DiscoveredLink(P_101, LT_101, 2, 0.0, 0.1, "pcmci+"),
        ]
    }
    result = consolidate(PHYSICAL_LINKS, found, GRID_DECISIONS)
    edges = edge_set(result.links)
    assert (P_101, FT_101, 0) not in edges and {(P_101, FT_101, k) for k in (1, 2, 3)} <= edges
    assert (LT_102, P_101, 1) in edges and (SP_102, P_101, 1) in edges
    rows = {(r["source"], r["target"]): r for r in result.table}
    assert "se elimina" in rows[(P_101, FT_101)]["reason"]
    assert "casi determinista" in rows[(P_101, LT_101)]["reason"]  # discrepancia clasificada
    assert "ningún método" in rows[(LT_101, LT_102)]["reason"]


def _var_data(seed: int = 0, n: int = 1500) -> pd.DataFrame:
    """X → Y con retardo 1 y Z independiente, en dos corridas."""
    rng = np.random.default_rng(seed)
    frames = []
    for run in range(2):
        x, y, z = (np.zeros(n) for _ in range(3))
        for t in range(1, n):
            x[t] = 0.6 * x[t - 1] + rng.normal()
            y[t] = 0.5 * y[t - 1] + 0.8 * x[t - 1] + rng.normal()
            z[t] = 0.5 * z[t - 1] + rng.normal()
        frames.append(
            pd.DataFrame({"run_id": run, "sim_time": np.arange(n) * 0.5, "X": x, "Y": y, "Z": z})
        )
    return pd.concat(frames, ignore_index=True)


def test_descubrimiento_recupera_una_estructura_conocida():
    data = _var_data()
    for links in (
        run_pcmci(data, 2, 0.01, variables=("X", "Y", "Z")),
        run_granger(data, 2, 0.01, variables=("X", "Y", "Z")),
    ):
        cross = {(lk.source, lk.target, lk.lag) for lk in links if lk.source != lk.target}
        assert ("X", "Y", 1) in cross
        assert not any(s == "Y" and t == "X" for s, t, _ in cross)
        assert not any("Z" in (s, t) for s, t, _ in cross)
        assert all(0 <= lk.p_value <= 1 and lk.lag_s == lk.lag * 0.5 for lk in links)


def test_scm_fisico_identifica_los_parametros_y_cumple_el_rmse(config, grid):
    model = PhysicsInformedSCM.from_config(config).fit(grid)
    nominal = {"a1": 0.5, "a2": 0.4, "kp": 1.5, "pump_tau": 0.5, "kc": 2.5, "ki": 0.015}
    for row in model.parameter_report(nominal):
        assert abs(row["error_pct"]) <= 10.0, row  # RF-31
    rmse = model.rmse(grid)
    assert rmse[LT_101] <= 0.2 and rmse[LT_102] <= 0.2 and rmse[FT_101] <= 1.0
    assert set(model.residual_stats) == {LT_101, LT_102, FT_101, P_101}


def test_prediccion_a_un_paso_coincide_con_la_vectorizada(config, grid):
    model = PhysicsInformedSCM.from_config(config).fit(grid)
    run = grid[grid["run_id"] == "r101"].iloc[:60]
    history = {tag: run[tag].tolist() for tag in (SP_102, P_101, FT_101, LT_101, LT_102)}
    one = model.predict_one_step(history)
    batch = model.predict_frame(run).iloc[-1]
    assert one == pytest.approx({tag: batch[tag] for tag in one})


def test_persistencia_reproduce_las_predicciones(config, grid, tmp_path):
    reference = consolidate(PHYSICAL_LINKS, {}, GRID_DECISIONS).links
    physics = PhysicsInformedSCM.from_config(config).fit(grid)
    regression = RegressionSCM(reference).fit(grid)
    clone = model_from_dict(json.loads(json.dumps(regression.to_dict())))
    pd.testing.assert_frame_equal(clone.predict_frame(grid), regression.predict_frame(grid))

    save_model(physics, build_prior_graph(reference), {"k_sigma": 3.0}, tmp_path / "m")
    loaded, graph, thresholds = load_model(tmp_path / "m")
    pd.testing.assert_frame_equal(loaded.predict_frame(grid), physics.predict_frame(grid))
    assert edge_set(links_from_graph(graph)) == edge_set(reference)
    assert thresholds == {"k_sigma": 3.0}
    (tmp_path / "m" / "scm.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        load_model(tmp_path / "m")


def test_entrenamiento_completo(config, grid, tmp_path):
    from fdisim.causal.training import train_causal_model

    train, val = tmp_path / "train.parquet", tmp_path / "val.parquet"
    grid[grid["run_id"] == "r101"].to_parquet(train)
    grid[grid["run_id"] == "r102"].to_parquet(val)
    manifest = json.loads(
        train_causal_model(train, tmp_path / "modelo", with_sensitivity=False).read_text(
            encoding="utf-8"
        )
    )
    assert all(manifest["criteria"].values()), manifest["criteria"]
    out = tmp_path / "modelo"
    for name in (
        "report.md",
        "report.json",
        "scm_regression.json",
        "graph_physical.graphml",
        "figures/grafo_referencia.png",
        "figures/residuos_validacion.png",
    ):
        assert (out / name).is_file(), name
    attacked = grid.assign(label=1)
    attacked.to_parquet(tmp_path / "malo.parquet")
    with pytest.raises(ValueError, match="bajo ataque"):
        train_causal_model(tmp_path / "malo.parquet", tmp_path / "x", with_sensitivity=False)
