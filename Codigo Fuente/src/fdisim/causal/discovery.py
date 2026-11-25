"""Descubrimiento causal a partir de datos de operación normal (RF-29).

- **PCMCI / PCMCI+** (tigramite): prueba de independencia condicional ParCorr (lineal) y
  parámetros ``tau_max`` y ``alpha``. PCMCI+ admite enlaces contemporáneos. Se declara que la
  consigna es exógena (ninguna variable la causa), lo que también orienta sus enlaces.
- **Causalidad de Granger condicional** (statsmodels): para cada variable endógena se ajusta un
  VAR por mínimos cuadrados con ``max_lag`` retardos de todas las variables. Una prueba F
  conjunta decide si una causa aporta, y las pruebas t de cada coeficiente indican sus retardos.
  Solo detecta enlaces retardados.

Las series de varias corridas se tratan como realizaciones independientes: los retardos nunca
cruzan la frontera entre corridas. Con ``block > 1`` cada serie se resume en promedios por
bloques de ``block`` muestras, lo que reduce el ruido de medición y vuelve visibles los efectos
lentos; los retardos quedan entonces en unidades de bloque (``lag_s`` los da en segundos).

Ambos métodos devuelven la misma lista de enlaces con retardo y valor p, para compararlos con
el grafo físico en ``graph_compare`` (estudio comparativo, actividad 3.1). Se ejecuta fuera de
línea (riesgo R5): la detección en línea usa el SCM ya ajustado.

Implementado en la Fase 5. Dependencias: tigramite, statsmodels.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from fdisim.causal.prior_graph import EXOGENOUS, NODES


@dataclass(frozen=True, slots=True)
class DiscoveredLink:
    source: str
    target: str
    lag: int
    p_value: float
    strength: float  # correlación parcial (PCMCI) o estadístico t del coeficiente (Granger)
    method: str
    orientation: str = "-->"  # "-->" orientado; "o-o" o "x-x": contemporáneo sin orientar
    lag_s: float = 0.0  # retardo en segundos


def series_by_run(
    data: Any, variables: Sequence[str] = NODES, block: int = 1
) -> dict[int, np.ndarray]:
    """Una matriz (tiempo × variables) por corrida, opcionalmente promediada por bloques."""
    groups = data.groupby("run_id", sort=True) if "run_id" in data.columns else [(0, data)]
    out = {}
    for k, (_, frame) in enumerate(groups):
        x = frame.sort_values("sim_time")[list(variables)].to_numpy(dtype=float)
        if block > 1:
            n = len(x) // block * block
            x = x[:n].reshape(-1, block, len(variables)).mean(axis=1)
        out[k] = x
    return out


def _period(data: Any) -> float:
    if "sim_time" not in data.columns:
        return 1.0
    first = data[data["run_id"] == data["run_id"].iloc[0]] if "run_id" in data.columns else data
    return float(np.median(np.diff(first["sim_time"].to_numpy()[:100])))


def _link_assumptions(variables: Sequence[str], tau_max: int) -> dict[int, dict]:
    """Enlaces permitidos: nada causa a una variable exógena; ella solo puede causar."""
    exo = {i for i, v in enumerate(variables) if v in EXOGENOUS}
    n = len(variables)
    out: dict[int, dict] = {j: {} for j in range(n)}
    for j in range(n):
        for i in range(n):
            for tau in range(tau_max + 1):
                if tau == 0 and i == j:
                    continue
                if j in exo and i != j:
                    continue  # nada causa a la consigna
                if tau > 0:
                    out[j][(i, -tau)] = "-?>"
                elif i in exo:
                    out[j][(i, 0)] = "-?>"
                elif j in exo:
                    continue
                else:
                    out[j][(i, 0)] = "o?o"
    for j in range(n):  # los contemporáneos desde una exógena deben ser simétricos
        for (i, lag), kind in list(out[j].items()):
            if lag == 0 and kind == "-?>":
                out[i][(j, 0)] = "<?-"
    return out


def run_pcmci(
    data: Any,
    tau_max: int = 3,
    alpha: float = 0.01,
    ci_test: str = "parcorr",
    plus: bool = True,
    block: int = 1,
    variables: Sequence[str] = NODES,
) -> list[DiscoveredLink]:
    """PCMCI+ (o PCMCI con ``plus=False``) sobre las corridas de ``data``."""
    from tigramite import data_processing as pp
    from tigramite.independence_tests.parcorr import ParCorr
    from tigramite.pcmci import PCMCI

    if ci_test != "parcorr":
        raise ValueError(f"Prueba de independencia no soportada: {ci_test}")
    series = series_by_run(data, variables, block)
    with warnings.catch_warnings():  # una sola corrida en modo «multiple» es válido
        warnings.simplefilter("ignore")
        frame = pp.DataFrame(series, var_names=list(variables), analysis_mode="multiple")
    pcmci = PCMCI(dataframe=frame, cond_ind_test=ParCorr(significance="analytic"), verbosity=0)
    assumptions = _link_assumptions(variables, tau_max)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if plus:
            results = pcmci.run_pcmciplus(
                tau_min=0, tau_max=tau_max, pc_alpha=alpha, link_assumptions=assumptions
            )
        else:
            results = pcmci.run_pcmci(
                tau_min=1,
                tau_max=tau_max,
                pc_alpha=alpha,
                alpha_level=alpha,
                link_assumptions={
                    j: {k: "-?>" for k in v if k[1] < 0} for j, v in assumptions.items()
                },
            )
    graph, val, pval = results["graph"], results["val_matrix"], results["p_matrix"]
    step = _period(data) * block
    method = "pcmci+" if plus else "pcmci"
    out = []
    n = len(variables)
    for i in range(n):
        for j in range(n):
            for tau in range(tau_max + 1):
                mark = str(graph[i, j, tau])
                if mark == "-->" or (tau == 0 and i < j and mark in ("o-o", "x-x")):
                    out.append(
                        DiscoveredLink(
                            variables[i],
                            variables[j],
                            tau,
                            float(pval[i, j, tau]),
                            float(val[i, j, tau]),
                            method,
                            mark,
                            tau * step,
                        )
                    )
    return out


def run_granger(
    data: Any,
    max_lag: int = 3,
    alpha: float = 0.01,
    block: int = 1,
    variables: Sequence[str] = NODES,
) -> list[DiscoveredLink]:
    """Causalidad de Granger condicional (VAR por mínimos cuadrados, pruebas F y t)."""
    import statsmodels.api as sm

    series = series_by_run(data, variables, block)
    n = len(variables)
    rows_x, rows_y = [], []
    for x in series.values():
        if len(x) <= max_lag:
            continue
        rows_y.append(x[max_lag:])
        rows_x.append(np.hstack([x[max_lag - lag : len(x) - lag] for lag in range(1, max_lag + 1)]))
    X = sm.add_constant(np.vstack(rows_x), has_constant="add")
    Y = np.vstack(rows_y)
    step = _period(data) * block

    def column(cause: int, lag: int) -> int:
        return 1 + (lag - 1) * n + cause

    out = []
    for j, target in enumerate(variables):
        if target in EXOGENOUS:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = sm.OLS(Y[:, j], X).fit()
            for i, cause in enumerate(variables):
                cols = [column(i, lag) for lag in range(1, max_lag + 1)]
                restriction = np.zeros((max_lag, X.shape[1]))
                restriction[range(max_lag), cols] = 1.0
                joint = float(fit.f_test(restriction).pvalue)
                if joint >= alpha:
                    continue
                lags = [
                    lag
                    for lag, c in zip(range(1, max_lag + 1), cols, strict=True)
                    if fit.pvalues[c] < alpha
                ]
                if not lags:  # la causa aporta en conjunto: se informa su retardo más fuerte
                    lags = [1 + int(np.argmax(np.abs([fit.tvalues[c] for c in cols])))]
                for lag in lags:
                    c = column(i, lag)
                    out.append(
                        DiscoveredLink(
                            cause,
                            target,
                            lag,
                            min(joint, float(fit.pvalues[c])),
                            float(fit.tvalues[c]),
                            "granger",
                            "-->",
                            lag * step,
                        )
                    )
    return out
