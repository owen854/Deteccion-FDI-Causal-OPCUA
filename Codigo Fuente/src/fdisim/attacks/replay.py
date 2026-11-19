"""Ataque de repetición (replay) (RF-19).

Fase de grabación: ``observe`` mantiene, por variable, los valores legítimos de los últimos
``record_s`` segundos anteriores a ``tₛ``. Así el ataque también puede armarse en caliente
(RF-23): la grabación ya está disponible en el instante en que se arma. Fase de reproducción:
``falsify`` devuelve la muestra grabada en la posición ``(t − tₛ) mod record_s`` (retención
de orden cero), de modo que la ventana se repite en bucle. La grabación no altera los datos en
tránsito.

Parámetros del escenario: ``record_s``.
Implementado en la Fase 4.
"""

from __future__ import annotations

import bisect
from collections import deque

from fdisim.attacks.base import AttackStrategy, register_attack
from fdisim.common.types import AttackType


@register_attack(AttackType.REPLAY)
class ReplayAttack(AttackStrategy):
    def __init__(self, spec) -> None:  # noqa: ANN001
        super().__init__(spec)
        record = float(spec.params.get("record_s", 0.0))
        if record <= 0:
            raise ValueError(f"{spec.attack_id}: el replay requiere 'record_s' positivo")
        self.record_s = record
        self._buffer: dict[str, deque[tuple[float, float]]] = {}
        self._frozen: dict[str, tuple[list[float], list[float]]] = {}

    def observe(self, tag: str, value: float, t: float) -> None:
        if not self.applies_to(tag) or t >= self.spec.start_s:
            return
        buf = self._buffer.setdefault(tag, deque())
        buf.append((t, value))
        while buf and buf[0][0] < t - self.record_s:
            buf.popleft()

    def recording(self, tag: str) -> list[tuple[float, float]]:
        """Muestras grabadas de ``tag`` en ``[tₛ − record_s, tₛ)``."""
        start = self.spec.start_s - self.record_s
        return [(t, v) for t, v in self._buffer.get(tag, ()) if t >= start - 1e-9]

    def falsify(self, tag: str, value: float, t: float) -> float:
        frozen = self._frozen.get(tag)
        if frozen is None:
            recorded = self.recording(tag)
            if not recorded:
                return value  # sin grabación no hay nada que reproducir
            origin = self.spec.start_s - self.record_s
            frozen = ([rt - origin for rt, _ in recorded], [rv for _, rv in recorded])
            self._frozen[tag] = frozen
        offsets, values = frozen
        position = (t - self.spec.start_s) % self.record_s
        index = bisect.bisect_right(offsets, position + 1e-9) - 1
        return values[max(index, 0)]
