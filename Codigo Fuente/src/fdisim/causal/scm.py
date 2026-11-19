"""Modelo causal estructural (SCM) del proceso (RF-31).

Cada variable endógena se predice a un paso a partir de sus padres causales observados, en la
rejilla de detección (Δ = ``detection.period_s``; la fila *t* contiene los valores en *t*).

- **Físico-informado** (``PhysicsInformedSCM``): balances de masa discretizados con las
  áreas de los tanques conocidas (geometría) y ``a1``, ``a2`` identificados por mínimos
  cuadrados; la bomba como sistema de primer orden y la ley de control PI en forma incremental::

      h1(t) = h1(t−1) + Δ/A1 · [q_in(t−1) − a1·√(2g·h1(t−1))]
      h2(t) = h2(t−1) + Δ/A2 · [a1·√(2g·h1(t−1)) − a2·√(2g·h2(t−1))]
      q_in(t) = k_p · ū(t),   ū(t) = (1−α)·ū(t−1) + α·u(t−1)
      u(t) = sat(u(t−1) + Kc·[e(t) − e(t−1)] + Ki·Δ·e(t)),   e = SP − h2

  El estado interno de la bomba ``ū`` se reconstruye con la historia de la orden P-101, que no
  tiene ruido de medición; así se evita el sesgo que introduciría estimar ``α`` con la medición
  ruidosa de FT-101 (errores en las variables).

- **Por regresión** (``RegressionSCM``): un modelo lineal por variable endógena sobre los padres
  (con sus retardos) del grafo de referencia consolidado.

Ambos estiman la distribución de los residuos a un paso en datos normales (media y desviación
por variable), que el detector de la Fase 6 usa para decidir. ``simulate`` (gemelo causal en
horizonte H, RF-33) llega en la Fase 6.

Implementado en la Fase 5. Dependencias: NumPy, SciPy, scikit-learn.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from fdisim.causal.prior_graph import CausalLink
from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102

ENDOGENOUS: tuple[str, ...] = (LT_101, LT_102, FT_101, P_101)
INPUTS: tuple[str, ...] = (SP_102, P_101, FT_101, LT_101, LT_102)


@dataclass(frozen=True, slots=True)
class ResidualStats:
    mean: float
    std: float


def _runs(data: Any) -> list[Any]:
    if "run_id" not in data.columns:
        return [data.sort_values("sim_time") if "sim_time" in data.columns else data]
    return [frame.sort_values("sim_time") for _, frame in data.groupby("run_id", sort=True)]


def _stack(frames: list[Any]) -> Any:
    import pandas as pd

    return pd.concat(frames).sort_index()


def residual_statistics(residuals: Any) -> dict[str, ResidualStats]:
    out = {}
    for tag in ENDOGENOUS:
        r = residuals[tag].dropna().to_numpy()
        out[tag] = (
            ResidualStats(float(r.mean()), float(r.std(ddof=1)))
            if r.size > 1
            else (ResidualStats(0.0, float("nan")))
        )
    return out


class StructuralCausalModel(ABC):
    kind: str = "abstract"
    residual_stats: dict[str, ResidualStats]

    @abstractmethod
    def fit(self, normal_data: Any) -> StructuralCausalModel:
        """Ajusta las ecuaciones y estima ``residual_stats`` en datos normales."""

    @abstractmethod
    def predict_frame(self, data: Any) -> Any:
        """Predicción a un paso de cada variable endógena para todas las filas de ``data``."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Representación serializable (JSON) del modelo ajustado (RF-32)."""

    def residuals(self, data: Any) -> Any:
        """Residuos a un paso ``medido − predicho`` (NaN donde falta historia)."""
        predicted = self.predict_frame(data)
        return data.loc[predicted.index, list(ENDOGENOUS)] - predicted[list(ENDOGENOUS)]

    def rmse(self, data: Any) -> dict[str, float]:
        res = self.residuals(data)
        return {tag: float(np.sqrt(np.nanmean(res[tag].to_numpy() ** 2))) for tag in ENDOGENOUS}

    def predict_one_step(self, history: Mapping[str, list[float]]) -> dict[str, float]:
        """Predicción para el último instante de ``history`` (listas en orden temporal).

        Las variables con padres contemporáneos (P-101 depende de SP y LT-102 en *t*) usan el
        último valor de la historia; las demás, los anteriores.
        """
        import pandas as pd

        frame = pd.DataFrame({tag: list(history[tag]) for tag in INPUTS})
        frame["sim_time"] = np.arange(len(frame), dtype=float)
        last = self.predict_frame(frame).iloc[-1]
        return {tag: float(last[tag]) for tag in ENDOGENOUS}

    def simulate(self, history: Mapping[str, list[float]], horizon: int) -> dict[str, float]:
        """Predicción en horizonte ``horizon`` (residuo multi-paso, RF-33)."""
        raise NotImplementedError("Fase 6 — RF-33: gemelo causal multi-paso")


# ---------------------------------------------------------------------- físico-informado
@dataclass(slots=True)
class PhysicsParams:
    a1: float = math.nan
    a2: float = math.nan
    kp: float = math.nan
    alpha: float = math.nan
    kc: float = math.nan
    ki: float = math.nan
    area1: float = 153.9
    area2: float = 153.9
    gravity: float = 981.0
    dt: float = 0.5
    out_min: float = 0.0
    out_max: float = 100.0

    @property
    def pump_tau(self) -> float:
        """Constante de tiempo de la bomba equivalente a ``alpha`` [s]."""
        return -self.dt / math.log(1.0 - self.alpha) if 0 < self.alpha < 1 else math.nan


class PhysicsInformedSCM(StructuralCausalModel):
    kind = "physics_informed"

    def __init__(self, params: PhysicsParams | None = None) -> None:
        self.params = params or PhysicsParams()
        self.residual_stats: dict[str, ResidualStats] = {}

    @classmethod
    def from_config(cls, config: Mapping[str, Any], dt: float | None = None) -> PhysicsInformedSCM:
        plant, control = config["plant"], config["control"]
        return cls(
            PhysicsParams(
                area1=float(plant["tank1"]["area_cm2"]),
                area2=float(plant["tank2"]["area_cm2"]),
                gravity=float(plant.get("gravity_cm_s2", 981.0)),
                dt=float(dt or config["detection"]["period_s"]),
                out_min=float(control.get("out_min", 0.0)),
                out_max=float(control.get("out_max", 100.0)),
            )
        )

    # -------------------------------------------------------------- identificación
    def fit(self, normal_data: Any) -> PhysicsInformedSCM:
        from scipy.optimize import minimize_scalar

        p = self.params
        cur, prev = self._pairs(normal_data)
        s1 = np.sqrt(2 * p.gravity * np.clip(prev[LT_101], 0, None))
        s2 = np.sqrt(2 * p.gravity * np.clip(prev[LT_102], 0, None))
        # Tanque 1: A1·Δh1/Δ − q_in = −a1·√(2g·h1)
        y1 = p.area1 * (cur[LT_101] - prev[LT_101]) / p.dt - prev[FT_101]
        p.a1 = float(-np.sum(y1 * s1) / np.sum(s1 * s1))
        # Tanque 2: A2·Δh2/Δ − a1·√(2g·h1) = −a2·√(2g·h2)
        y2 = p.area2 * (cur[LT_102] - prev[LT_102]) / p.dt - p.a1 * s1
        p.a2 = float(-np.sum(y2 * s2) / np.sum(s2 * s2))

        # Bomba: para cada α, k_p por mínimos cuadrados sobre ū reconstruido con P-101
        runs = _runs(normal_data)

        def pump_fit(alpha: float) -> tuple[float, float]:
            ubar = np.concatenate([self._pump_state(r[P_101].to_numpy(), alpha) for r in runs])
            q = np.concatenate([r[FT_101].to_numpy() for r in runs])
            mask = np.concatenate([np.arange(len(r)) > 0 for r in runs])
            kp = float(np.sum(ubar[mask] * q[mask]) / np.sum(ubar[mask] ** 2))
            return kp, float(np.mean((q[mask] - kp * ubar[mask]) ** 2))

        best = minimize_scalar(
            lambda a: pump_fit(a)[1],
            bounds=(0.05, 0.999),
            method="bounded",
            options={"xatol": 1e-5},
        )
        p.alpha = float(best.x)
        p.kp = pump_fit(p.alpha)[0]

        # Controlador PI incremental, solo en muestras sin saturación
        e_cur, e_prev = cur[SP_102] - cur[LT_102], prev[SP_102] - prev[LT_102]
        du = cur[P_101] - prev[P_101]
        free = (cur[P_101] > p.out_min + 1e-6) & (cur[P_101] < p.out_max - 1e-6)
        design = np.column_stack([(e_cur - e_prev)[free], (p.dt * e_cur)[free]])
        coef, *_ = np.linalg.lstsq(design, du[free], rcond=None)
        p.kc, p.ki = float(coef[0]), float(coef[1])

        self.residual_stats = residual_statistics(self.residuals(normal_data))
        return self

    @staticmethod
    def _pump_state(u: np.ndarray, alpha: float) -> np.ndarray:
        """ū(t) = (1−α)·ū(t−1) + α·u(t−1), con ū(0) = u(0) (arranque en equilibrio)."""
        from scipy.signal import lfilter

        if len(u) == 0:
            return u
        shifted = np.concatenate(([u[0]], u[:-1]))
        state, _ = lfilter([alpha], [1.0, -(1.0 - alpha)], shifted, zi=[(1.0 - alpha) * u[0]])
        return state

    def _pairs(self, data: Any) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        cur: dict[str, list[np.ndarray]] = {tag: [] for tag in INPUTS}
        prev: dict[str, list[np.ndarray]] = {tag: [] for tag in INPUTS}
        for frame in _runs(data):
            for tag in INPUTS:
                x = frame[tag].to_numpy(dtype=float)
                cur[tag].append(x[1:])
                prev[tag].append(x[:-1])
        return (
            {tag: np.concatenate(v) for tag, v in cur.items()},
            {tag: np.concatenate(v) for tag, v in prev.items()},
        )

    # -------------------------------------------------------------- predicción
    def predict_frame(self, data: Any) -> Any:
        import pandas as pd

        p = self.params
        out = []
        for frame in _runs(data):
            h1, h2 = frame[LT_101].to_numpy(float), frame[LT_102].to_numpy(float)
            q, u = frame[FT_101].to_numpy(float), frame[P_101].to_numpy(float)
            sp = frame[SP_102].to_numpy(float)
            n = len(frame)
            pred = {tag: np.full(n, np.nan) for tag in ENDOGENOUS}
            if n > 1:
                s1 = np.sqrt(2 * p.gravity * np.clip(h1[:-1], 0, None))
                s2 = np.sqrt(2 * p.gravity * np.clip(h2[:-1], 0, None))
                pred[LT_101][1:] = h1[:-1] + p.dt / p.area1 * (q[:-1] - p.a1 * s1)
                pred[LT_102][1:] = h2[:-1] + p.dt / p.area2 * (p.a1 * s1 - p.a2 * s2)
                pred[FT_101][1:] = p.kp * self._pump_state(u, p.alpha)[1:]
                e = sp - h2
                du = p.kc * (e[1:] - e[:-1]) + p.ki * p.dt * e[1:]
                pred[P_101][1:] = np.clip(u[:-1] + du, p.out_min, p.out_max)
            out.append(pd.DataFrame(pred, index=frame.index))
        return _stack(out)

    # -------------------------------------------------------------- informe y persistencia
    def parameter_report(self, nominal: Mapping[str, float]) -> list[dict[str, float]]:
        """Parámetros identificados frente a los nominales (criterio ±10 % de RF-31)."""
        rows = []
        values = {**asdict(self.params), "pump_tau": self.params.pump_tau}
        for name, nominal_value in nominal.items():
            value = values[name]
            rows.append(
                {
                    "parameter": name,
                    "identified": value,
                    "nominal": nominal_value,
                    "error_pct": 100.0 * (value - nominal_value) / nominal_value,
                }
            )
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "params": asdict(self.params),
            "residual_stats": {k: asdict(v) for k, v in self.residual_stats.items()},
            "equations": {
                LT_101: "h1(t) = h1(t-1) + dt/A1*(q_in(t-1) - a1*sqrt(2g*h1(t-1)))",
                LT_102: "h2(t) = h2(t-1) + dt/A2*(a1*sqrt(2g*h1(t-1)) - a2*sqrt(2g*h2(t-1)))",
                FT_101: "q_in(t) = kp*ubar(t); ubar(t) = (1-alpha)*ubar(t-1) + alpha*u(t-1)",
                P_101: "u(t) = sat(u(t-1) + kc*(e(t)-e(t-1)) + ki*dt*e(t)); e = SP - h2",
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PhysicsInformedSCM:
        model = cls(PhysicsParams(**data["params"]))
        model.residual_stats = {k: ResidualStats(**v) for k, v in data["residual_stats"].items()}
        return model


# ---------------------------------------------------------------------- por regresión
@dataclass(slots=True)
class LinearEquation:
    target: str
    features: list[tuple[str, int]]  # (fuente, retardo)
    coef: list[float] = field(default_factory=list)
    intercept: float = 0.0


class RegressionSCM(StructuralCausalModel):
    kind = "regression"

    def __init__(self, links: Iterable[CausalLink]) -> None:
        links = list(links)
        self.equations = {
            tag: LinearEquation(
                tag, sorted({(lk.source, int(lk.lag)) for lk in links if lk.target == tag})
            )
            for tag in ENDOGENOUS
        }
        self.residual_stats: dict[str, ResidualStats] = {}

    def _design(self, frame: Any, equation: LinearEquation) -> np.ndarray:
        columns = []
        for source, lag in equation.features:
            x = frame[source].to_numpy(float)
            columns.append(np.concatenate((np.full(lag, np.nan), x[: len(x) - lag])) if lag else x)
        return np.column_stack(columns) if columns else np.empty((len(frame), 0))

    def fit(self, normal_data: Any) -> RegressionSCM:
        from sklearn.linear_model import LinearRegression

        runs = _runs(normal_data)
        for tag, equation in self.equations.items():
            X = np.vstack([self._design(r, equation) for r in runs])
            y = np.concatenate([r[tag].to_numpy(float) for r in runs])
            ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
            reg = LinearRegression().fit(X[ok], y[ok])
            equation.coef = [float(c) for c in reg.coef_]
            equation.intercept = float(reg.intercept_)
        self.residual_stats = residual_statistics(self.residuals(normal_data))
        return self

    def predict_frame(self, data: Any) -> Any:
        import pandas as pd

        out = []
        for frame in _runs(data):
            pred = {}
            for tag, equation in self.equations.items():
                X = self._design(frame, equation)
                pred[tag] = X @ np.asarray(equation.coef) + equation.intercept
            out.append(pd.DataFrame(pred, index=frame.index))
        return _stack(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "equations": {
                tag: {
                    "features": [list(f) for f in eq.features],
                    "coef": eq.coef,
                    "intercept": eq.intercept,
                }
                for tag, eq in self.equations.items()
            },
            "residual_stats": {k: asdict(v) for k, v in self.residual_stats.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RegressionSCM:
        model = cls(())
        for tag, eq in data["equations"].items():
            model.equations[tag] = LinearEquation(
                tag,
                [(str(s), int(lag)) for s, lag in eq["features"]],
                list(eq["coef"]),
                float(eq["intercept"]),
            )
        model.residual_stats = {k: ResidualStats(**v) for k, v in data["residual_stats"].items()}
        return model


def model_from_dict(data: Mapping[str, Any]) -> StructuralCausalModel:
    kinds = {PhysicsInformedSCM.kind: PhysicsInformedSCM, RegressionSCM.kind: RegressionSCM}
    try:
        return kinds[data["kind"]].from_dict(data)
    except KeyError:
        raise ValueError(f"Tipo de SCM desconocido: {data.get('kind')}") from None
