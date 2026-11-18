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


INITIAL_VALUES: dict[str, float] = {
    LT_101: 16.0,
    LT_102: 25.0,
    FT_101: 88.6,
    P_101: 59.0,
    SP_102: 25.0,
    FT_102: 88.6,
}

# Unidades UNECE (OPC UA Parte 8): NamespaceUri de CEFACT y código común
UNECE_NAMESPACE = "http://www.opcfoundation.org/UA/units/un/cefact"
UNECE_CODES: dict[str, tuple[str, str]] = {
    "cm": ("CMT", "centímetro"),
    "cm³/s": ("2J", "centímetro cúbico por segundo"),
    "%": ("P1", "porcentaje"),
    "s": ("SEC", "segundo"),
}


def variable_by_tag(tag: str) -> VariableSpec:
    for spec in PLANT_VARIABLES + STATUS_VARIABLES:
        if spec.tag == tag:
            return spec
    raise KeyError(f"Etiqueta desconocida en el modelo de información: {tag}")


def unece_unit_id(code: str) -> int:
    """UnitId de OPC UA para un código común UNECE (bytes ASCII en big-endian)."""
    return int.from_bytes(code.encode("ascii"), "big")


async def build_address_space(
    server: Any, namespace_index: int, include_optional: bool = False
) -> dict[str, Any]:
    """Crea los nodos en ``server`` (asyncua) y devuelve ``{tag: nodo}``.

    Cada variable analógica es de tipo AnalogItemType con EngineeringUnits y EURange
    (Parte 8) y su AccessLevel: solo lectura para sensores, lectura/escritura para P-101 y
    LIC-102.SP (RF-10).
    """
    from asyncua import ua

    idx = namespace_index
    root = await server.nodes.objects.add_object(
        ua.NodeId(ROOT_OBJECT, idx), ua.QualifiedName(ROOT_OBJECT, idx)
    )
    folders: dict[str, Any] = {}
    nodes: dict[str, Any] = {}
    for spec in PLANT_VARIABLES + STATUS_VARIABLES:
        if spec.optional and not include_optional:
            continue
        folder_name = spec.browse_path[0]
        if folder_name not in folders:
            folders[folder_name] = await root.add_object(
                ua.NodeId(f"{ROOT_OBJECT}.{folder_name}", idx), ua.QualifiedName(folder_name, idx)
            )
        nodes[spec.tag] = await _add_variable(folders[folder_name], idx, spec)
    return nodes


async def _add_variable(parent: Any, idx: int, spec: VariableSpec) -> Any:
    from asyncua import Node, ua

    name = spec.browse_path[-1]
    nodeid = ua.NodeId(spec.node_name, idx)
    if spec.data_type == "Boolean":
        node = await parent.add_variable(
            nodeid, ua.QualifiedName(name, idx), False, ua.VariantType.Boolean
        )
    else:
        item = ua.AddNodesItem()
        item.RequestedNewNodeId = nodeid
        item.BrowseName = ua.QualifiedName(name, idx)
        item.NodeClass = ua.NodeClass.Variable
        item.ParentNodeId = parent.nodeid
        item.ReferenceTypeId = ua.NodeId(ua.ObjectIds.HasComponent)
        item.TypeDefinition = ua.NodeId(
            ua.ObjectIds.AnalogItemType if spec.eu_range else ua.ObjectIds.BaseDataVariableType
        )
        attrs = ua.VariableAttributes()
        attrs.DisplayName = ua.LocalizedText(
            f"{name} ({spec.tag})" if "." not in spec.tag else name
        )
        attrs.Description = ua.LocalizedText(spec.description)
        attrs.DataType = ua.NodeId(ua.ObjectIds.Double)
        attrs.Value = ua.Variant(INITIAL_VALUES.get(spec.tag, 0.0), ua.VariantType.Double)
        attrs.ValueRank = ua.ValueRank.Scalar
        attrs.ArrayDimensions = None
        mask = ua.AccessLevel.CurrentRead.mask
        if spec.writable:
            mask |= ua.AccessLevel.CurrentWrite.mask
        attrs.AccessLevel = mask
        attrs.UserAccessLevel = mask
        attrs.WriteMask = 0
        attrs.UserWriteMask = 0
        attrs.Historizing = False
        item.NodeAttributes = attrs
        result = (await parent.session.add_nodes([item]))[0]
        result.StatusCode.check()
        node = Node(parent.session, result.AddedNodeId)

    if spec.eu_range is not None:
        low, high = spec.eu_range
        await node.add_property(
            ua.NodeId(f"{spec.node_name}.EURange", idx),
            ua.QualifiedName("EURange", 0),
            ua.Range(Low=low, High=high),
        )
    if spec.unit in UNECE_CODES:
        code, description = UNECE_CODES[spec.unit]
        await node.add_property(
            ua.NodeId(f"{spec.node_name}.EngineeringUnits", idx),
            ua.QualifiedName("EngineeringUnits", 0),
            ua.EUInformation(
                NamespaceUri=UNECE_NAMESPACE,
                UnitId=unece_unit_id(code),
                DisplayName=ua.LocalizedText(spec.unit),
                Description=ua.LocalizedText(description),
            ),
        )
    return node
