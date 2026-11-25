"""Cálculo de residuos causales (RF-33).

Sobre la rejilla de detección (Δ = ``detection.period_s``) y con el SCM físico-informado:

- **A un paso** (``<tag>:1``), para las cuatro variables endógenas:
  ``r_i(t) = x_i^obs(t) − f_i(padres observados)``. Son sensibles a cambios bruscos y a las
  variables cuya ecuación tiene una entrada directa (caudal frente a la orden de la bomba).
  El de FT-101 tolera el instante de aplicación de la orden (en red llega a la planta con la
  latencia del enlace): mide la distancia del caudal al intervalo entre «orden aún no
  aplicada» y «orden aplicada todo el periodo».
- **En horizonte H** (``LT-101:H`` y ``LT-102:H``): diferencia entre el nivel observado y el
  gemelo causal que lo integra H pasos desde su valor en ``t − H`` con sus padres observados
  (``PhysicsInformedSCM.simulate``). Un sesgo o una rampa lenta sobre un nivel desplaza el
  ancla pero no la física, así que el residuo crece con H; por eso se usan dos horizontes:
  uno corto (sensible al inicio del ataque) y uno largo (sensible a desviaciones sostenidas).

Ambos se normalizan con las estadísticas de operación normal (entrenamiento):
``z = (r − μ) / σ``. El cálculo es incremental (una muestra a la vez), de modo que el monitor
en línea y el reprocesamiento de corridas guardadas ejecutan exactamente el mismo código
(RF-38).

Implementado en la Fase 6.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence

from fdisim.causal.scm import PhysicsInformedSCM
from fdisim.common.types import FT_101, LT_101, LT_102, P_101, SP_102

ONE_STEP_TAGS: tuple[str, ...] = (LT_101, LT_102, FT_101, P_101)
HORIZON_TAGS: tuple[str, ...] = (LT_101, LT_102)


def stream_names(horizons: Sequence[int]) -> tuple[str, ...]:
    """Nombres de los residuos: ``<tag>:1`` y ``<tag>:<H>`` para cada horizonte."""
    return (
        *(f"{tag}:1" for tag in ONE_STEP_TAGS),
        *(f"{tag}:{h}" for h in horizons for tag in HORIZON_TAGS),
    )


def stream_tag(stream: str) -> str:
    """Variable a la que pertenece un residuo (``"LT-102:20"`` → ``"LT-102"``)."""
    return stream.rsplit(":", 1)[0]


class ResidualComputer:
    def __init__(
        self,
        scm: PhysicsInformedSCM,
        horizons: Sequence[int] = (20, 120),
        stats: Mapping[str, tuple[float, float]] | None = None,
    ) -> None:
        if not isinstance(scm, PhysicsInformedSCM):
            raise TypeError("El gemelo causal necesita el SCM físico-informado")
        if any(h < 2 for h in horizons):
            raise ValueError("Los horizontes deben ser de al menos 2 pasos")
        self.scm = scm
        self.horizons = tuple(sorted(int(h) for h in horizons))
        self.names = stream_names(self.horizons)
        self.stats = dict(stats or {})
        self.history_len = max(self.horizons) + 1
        self.reset()

    def reset(self) -> None:
        self._h1: deque[float] = deque(maxlen=self.history_len)
        self._h2: deque[float] = deque(maxlen=self.history_len)
        self._q: deque[float] = deque(maxlen=self.history_len)
        self._inflow2: deque[float] = deque(maxlen=self.history_len)  # a1·√(2g·h1) observado
        self._prev: dict[str, float] | None = None
        self._ubar = math.nan

    # ------------------------------------------------------------------
    def update(self, values: Mapping[str, float]) -> dict[str, float]:
        """Añade la muestra al historial y devuelve los residuos crudos (NaN sin historia)."""
        p = self.scm.params
        two_g = 2.0 * p.gravity
        h1, h2 = float(values[LT_101]), float(values[LT_102])
        q, u, sp = float(values[FT_101]), float(values[P_101]), float(values[SP_102])
        out = dict.fromkeys(self.names, math.nan)

        prev = self._prev
        if prev is None:
            self._ubar = u  # arranque en equilibrio, igual que PhysicsInformedSCM._pump_state
        else:
            s1 = math.sqrt(two_g * max(prev["h1"], 0.0))
            s2 = math.sqrt(two_g * max(prev["h2"], 0.0))
            out[f"{LT_101}:1"] = h1 - (prev["h1"] + p.dt / p.area1 * (prev["q"] - p.a1 * s1))
            out[f"{LT_102}:1"] = h2 - (prev["h2"] + p.dt / p.area2 * (p.a1 * s1 - p.a2 * s2))
            # Bomba con tolerancia al instante de aplicación de la orden: en red, la orden
            # escrita en (t−1, t] llega a la planta con la latencia del enlace, así que el
            # estado real queda entre «aún no aplicada» (ū_a, ecuación del SCM) y «aplicada
            # todo el intervalo» (ū_b). El residuo es la distancia del caudal a ese intervalo;
            # fuera de línea, donde ū_a es exacto, apenas cambia su distribución.
            ubar_prev = self._ubar
            self._ubar = (1.0 - p.alpha) * ubar_prev + p.alpha * prev["u"]
            ubar_b = (1.0 - p.alpha) * ubar_prev + p.alpha * u
            low, high = sorted((p.kp * self._ubar, p.kp * ubar_b))
            out[f"{FT_101}:1"] = (q - high) if q > high else ((q - low) if q < low else 0.0)
            e, e_prev = sp - h2, prev["sp"] - prev["h2"]
            u_pred = prev["u"] + p.kc * (e - e_prev) + p.ki * p.dt * e
            out[f"{P_101}:1"] = u - min(max(u_pred, p.out_min), p.out_max)

        self._h1.append(h1)
        self._h2.append(h2)
        self._q.append(q)
        self._inflow2.append(p.a1 * math.sqrt(two_g * max(h1, 0.0)))
        n = len(self._h1)
        k1, k2 = p.dt / p.area1, p.dt / p.area2
        for horizon in self.horizons:
            if n <= horizon:
                continue
            start = n - 1 - horizon
            a, b = self._h1[start], self._h2[start]
            for j in range(start, n - 1):
                a += k1 * (self._q[j] - p.a1 * math.sqrt(two_g * max(a, 0.0)))
                b += k2 * (self._inflow2[j] - p.a2 * math.sqrt(two_g * max(b, 0.0)))
            out[f"{LT_101}:{horizon}"] = h1 - a
            out[f"{LT_102}:{horizon}"] = h2 - b

        self._prev = {"h1": h1, "h2": h2, "q": q, "u": u, "sp": sp}
        return out

    def normalize(self, raw: Mapping[str, float]) -> dict[str, float]:
        """``z = (r − μ) / σ`` con las estadísticas de operación normal de cada residuo."""
        z = {}
        for name, value in raw.items():
            mean, std = self.stats.get(name, (0.0, 1.0))
            z[name] = (value - mean) / std if math.isfinite(value) and std > 0 else math.nan
        return z
