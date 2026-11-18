"""Modelo de información OPC UA de la planta (RF-10; ERS §5; Informe OE1 §3.3).

Espacio de direcciones::

    Objects
    └── PlantaDosTanques            (TwoTankProcessType)
        ├── Tanque1/Nivel           LT-101      Double  cm      L
        ├── Tanque2/Nivel           LT-102      Double  cm      L
        ├── Tanque2/CaudalSalida    FT-102      Double  cm³/s   L   (opcional)
        ├── Bomba/Caudal            FT-101      Double  cm³/s   L
        ├── Bomba/Comando           P-101       Double  %       L/E
        ├── Control/Consigna        LIC-102.SP  Double  cm      L/E
        └── Estado/{TiempoSimulado, EnEjecucion}

La especificación (``PLANT_VARIABLES``) es la fuente única de verdad: la usan el servidor de
planta, el gateway (que replica el espacio de direcciones) y los clientes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdisim.common.types import FT_101, FT_102, LT_101, LT_102, P_101, SP_102

NAMESPACE_URI = "urn:unipamplona:siddfai:fdisim"
ROOT_OBJECT = "PlantaDosTanques"
OBJECT_TYPE = "TwoTankProcessType"


@dataclass(frozen=True, slots=True)
class VariableSpec:
    tag: str
    browse_path: tuple[str, ...]  # relativo a ROOT_OBJECT
    description: str
    unit: str
    eu_range: tuple[float, float] | None
    writable: bool
    data_type: str = "Double"
    optional: bool = False

    @property
    def node_name(self) -> str:
        """Identificador de cadena del NodeId, p. ej. ``Tanque2.Nivel``."""
        return ".".join(self.browse_path)


PLANT_VARIABLES: tuple[VariableSpec, ...] = (
    VariableSpec(LT_101, ("Tanque1", "Nivel"), "Nivel del tanque 1 (h1)", "cm", (0.0, 50.0), False),
    VariableSpec(LT_102, ("Tanque2", "Nivel"), "Nivel del tanque 2 (h2)", "cm", (0.0, 50.0), False),
    VariableSpec(
        FT_101, ("Bomba", "Caudal"), "Caudal de entrada (q_in)", "cm³/s", (0.0, 150.0), False
    ),
    VariableSpec(P_101, ("Bomba", "Comando"), "Comando de la bomba (u)", "%", (0.0, 100.0), True),
    VariableSpec(
        SP_102, ("Control", "Consigna"), "Consigna de nivel del tanque 2", "cm", (5.0, 45.0), True
    ),
    VariableSpec(
        FT_102,
        ("Tanque2", "CaudalSalida"),
        "Caudal de salida del tanque 2",
        "cm³/s",
        (0.0, 150.0),
        False,
        optional=True,
    ),
)

STATUS_VARIABLES: tuple[VariableSpec, ...] = (
    VariableSpec("SIM.TIME", ("Estado", "TiempoSimulado"), "Tiempo simulado", "s", None, False),
    VariableSpec(
        "SIM.RUNNING",
        ("Estado", "EnEjecucion"),
        "Simulación en ejecución",
        "",
        None,
        False,
        data_type="Boolean",
    ),
)


def variable_by_tag(tag: str) -> VariableSpec:
    for spec in PLANT_VARIABLES + STATUS_VARIABLES:
        if spec.tag == tag:
            return spec
    raise KeyError(f"Etiqueta desconocida en el modelo de información: {tag}")


async def build_address_space(
    server: Any, namespace_index: int, include_optional: bool = False
) -> dict[str, Any]:
    """Crea los nodos en ``server`` (asyncua) y devuelve ``{tag: nodo}``.

    Cada variable analógica lleva EngineeringUnits y EURange (Parte 8) y su AccessLevel.
    """
    raise NotImplementedError("Fase 3 — RF-10: construcción del espacio de direcciones")
