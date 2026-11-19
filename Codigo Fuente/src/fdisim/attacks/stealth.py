"""Restricciones de sigilo (RF-20).

Sea ``δ(k) = yₐ(k) − y(k)`` la desviación que inyecta el atacante. Con sigilo activo:

- **Tasa limitada:** ``|δ(k) − δ(k−1)| ≤ ρ_max·Δt``. Se limita la desviación y no el valor
  publicado: así el ataque entra de forma gradual, sin escalones, y la señal conserva su
  dinámica y su ruido natural. Limitar el valor publicado recortaría también el ruido del
  sensor (σ = 0,1 cm frente a ρ·Δt = 0,05 cm) y la señal falsa quedaría delatoramente suave.
- **Salida gradual:** ``|δ(k)| ≤ ρ_max·(t_e − t)``: la desviación vuelve a cero al final de la
  ventana, de modo que tampoco hay un escalón al terminar y la falsificación queda dentro del
  intervalo etiquetado.
- **Envolvente operativa:** ``yₐ ← clip(yₐ, y_min, y_max)``, para que ningún valor falso salga
  del rango plausible (un detector por umbrales estáticos no lo detecta trivialmente).

El inyector informa en cada muestra la desviación publicada con ``track``.

Implementado en la Fase 4.
"""

from __future__ import annotations

from fdisim.common.types import StealthSpec


class StealthFilter:
    def __init__(self, spec: StealthSpec) -> None:
        self.spec = spec
        self._last_delta: dict[str, tuple[float, float]] = {}

    def track(self, tag: str, published: float, original: float, t: float) -> None:
        """Registra la desviación publicada de ``tag`` (cero cuando no hay ataque)."""
        self._last_delta[tag] = (t, published - original)

    def apply(
        self,
        tag: str,
        fake_value: float,
        t: float,
        original: float | None = None,
        t_end: float | None = None,
    ) -> float:
        if not self.spec.enabled:
            return fake_value
        value = fake_value
        rate = self.spec.max_rate_per_s
        if rate is not None and original is not None:
            delta = fake_value - original
            # Sin historial, el ataque parte de desviación cero (nunca con un escalón).
            prev_t, prev_delta = self._last_delta.get(tag, (t, 0.0))
            step = rate * max(0.0, t - prev_t)
            delta = min(max(delta, prev_delta - step), prev_delta + step)
            if t_end is not None:
                room = rate * max(0.0, t_end - t)
                delta = min(max(delta, -room), room)
            value = original + delta
        if self.spec.envelope is not None:
            low, high = self.spec.envelope
            value = min(max(value, low), high)
        return value
