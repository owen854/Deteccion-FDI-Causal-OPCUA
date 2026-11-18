# Modelo de información OPC UA

Fuente única de verdad en el código: `src/fdisim/opcua/information_model.py` (`PLANT_VARIABLES`). Requerimientos: RF-10, RF-14; ERS §5.

- Namespace URI: `urn:unipamplona:siddfai:fdisim`
- Objeto raíz: `Objects/PlantaDosTanques` (tipo `TwoTankProcessType`)
- NodeId de cadena: `ns=<idx>;s=<Objeto>.<Variable>` (p. ej. `ns=2;s=Tanque2.Nivel`)

```
Objects
└── PlantaDosTanques                (TwoTankProcessType)
    ├── Tanque1
    │   └── Nivel                   LT-101      Double  cm      L
    ├── Tanque2
    │   ├── Nivel                   LT-102      Double  cm      L
    │   └── CaudalSalida            FT-102      Double  cm³/s   L    (opcional)
    ├── Bomba
    │   ├── Caudal                  FT-101      Double  cm³/s   L
    │   └── Comando                 P-101       Double  %       L/E
    ├── Control
    │   └── Consigna                LIC-102.SP  Double  cm      L/E
    └── Estado
        ├── TiempoSimulado                      Double  s       L
        └── EnEjecucion                         Boolean         L
```

| Etiqueta | Variable | Rango (EURange) | Acceso | Rol causal |
|---|---|---|---|---|
| LT-101 | Nivel tanque 1 (h1) | 0–50 cm | L | Endógena (estado) |
| LT-102 | Nivel tanque 2 (h2) | 0–50 cm | L | Endógena; variable controlada |
| FT-101 | Caudal de entrada (q_in) | 0–150 cm³/s | L | Endógena |
| P-101 | Comando de bomba (u) | 0–100 % | L/E | Endógena (ley de control) |
| LIC-102.SP | Consigna de nivel (SP) | 5–45 cm | L/E | Exógena |

Las variables analógicas usan `AnalogItemType` con `EngineeringUnits` y `EURange` (OPC UA Parte 8). Cada valor se publica como `DataValue` con `StatusCode`, `SourceTimestamp` (instante del paso de simulación) y `ServerTimestamp`.

## Seguridad por enlace

| Enlace | Cliente → servidor | Modo / política por defecto | Autenticación |
|---|---|---|---|
| Campo | gateway → servidor de planta | SignAndEncrypt / Basic256Sha256 | certificado de aplicación + usuario |
| Control | controlador → gateway | SignAndEncrypt / Basic256Sha256 | certificado de aplicación + usuario |
| Supervisión | monitor / HMI → gateway | SignAndEncrypt / Basic256Sha256 | certificado de aplicación + usuario |

Los certificados se generan con `scripts/generar_certificados.py` y nunca se versionan.
