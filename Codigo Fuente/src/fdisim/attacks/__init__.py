"""M4 — Inyección de datos falsos (RF-16 a RF-24).

Importar este paquete registra las estrategias disponibles (sesgo, rampa, replay) en el
registro de ``attacks.base``. Para añadir un ataque nuevo basta con crear un módulo con una
subclase de ``AttackStrategy`` decorada con ``@register_attack`` e importarlo aquí (RNF-16).
"""

from fdisim.attacks import bias, ramp, replay  # noqa: F401  (registro de estrategias)
from fdisim.attacks.base import AttackStrategy, create_attack, register_attack, registered_attacks

__all__ = ["AttackStrategy", "create_attack", "register_attack", "registered_attacks"]
