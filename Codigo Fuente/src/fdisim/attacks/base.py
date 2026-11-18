"""Interfaz abstracta y registro de estrategias de ataque FDI (RF-16, RNF-16).

Notación (Informe OE1 §4.3): ``y`` es el valor legítimo, ``yₐ`` el valor que reciben los
clientes y ``[tₛ, tₑ)`` la ventana de ataque en tiempo simulado.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar, TypeVar

from fdisim.common.types import AttackSpec, AttackType


class AttackStrategy(ABC):
    """Estrategia que falsifica los valores de sus variables objetivo dentro de su ventana."""

    type: ClassVar[AttackType]

    def __init__(self, spec: AttackSpec) -> None:
        self.spec = spec

    def applies_to(self, tag: str) -> bool:
        return tag in self.spec.targets

    def is_active(self, t: float) -> bool:
        return self.spec.is_active(t)

    def observe(self, tag: str, value: float, t: float) -> None:  # noqa: B027
        """Recibe cada valor legítimo antes de falsificarlo (lo usa el replay para grabar).

        Por defecto no hace nada.
        """

    @abstractmethod
    def falsify(self, tag: str, value: float, t: float) -> float:
        """Devuelve ``yₐ`` para ``tag`` en el instante ``t``.

        Solo se invoca dentro de la ventana de ataque.
        """


_A = TypeVar("_A", bound=type[AttackStrategy])
_REGISTRY: dict[AttackType, type[AttackStrategy]] = {}


def register_attack(attack_type: AttackType) -> Callable[[_A], _A]:
    """Decorador que registra una estrategia para un ``AttackType``."""

    def decorator(cls: _A) -> _A:
        if attack_type in _REGISTRY:
            raise ValueError(f"Ataque ya registrado: {attack_type.value}")
        cls.type = attack_type
        _REGISTRY[attack_type] = cls
        return cls

    return decorator


def create_attack(spec: AttackSpec) -> AttackStrategy:
    """Instancia la estrategia registrada para ``spec.type``."""
    try:
        cls = _REGISTRY[spec.type]
    except KeyError:
        raise ValueError(f"Tipo de ataque no registrado: {spec.type}") from None
    return cls(spec)


def registered_attacks() -> tuple[AttackType, ...]:
    return tuple(_REGISTRY)
