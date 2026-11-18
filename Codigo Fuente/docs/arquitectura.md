# Arquitectura de FDISim-OPCUA

Resultado de la Fase 0 del Plan de Gestión (Documento 03, §4). Requerimientos: Documento 01 (ERS).

![Arquitectura](diagramas/arquitectura_sistema.png)

## Principios

1. **Red industrial real en un solo equipo.** Cada componente es un proceso independiente que se comunica por OPC UA sobre TCP local, con la misma pila (asyncua) y la misma seguridad que en un despliegue real.
2. **Plano de datos y plano de experimento separados.** Las variables del proceso viajan solo por OPC UA (y ahí ocurre el ataque). La verdad de terreno, las etiquetas y los comandos del experimento usan colas locales confiables (`common/bus.py`). El detector nunca ve la verdad de terreno.
3. **Nodo comprometido realista.** El ataque ocurre en un gateway agregador autorizado, que termina el canal seguro en cada salto. Por eso los datos falsos llegan firmados y cifrados (Informe OE1, §3.6).
4. **Un solo código para los modos en red y offline.** Planta, inyector y detectores son las mismas clases; el modo offline solo elimina la red, para hacer campañas grandes y reproducibles (RF-38).
5. **Extensibilidad por registro.** Ataques y detectores se registran por nombre (`@register_attack`, `@register_detector`) sin tocar el núcleo (RNF-16).

## Componentes y flujo

```mermaid
flowchart LR
    subgraph Campo
        P[Planta de dos tanques<br/>process.Plant] --- PS[Servidor OPC UA de planta<br/>:4840]
    end
    subgraph Control y supervisión
        GW[Gateway agregador :4841<br/>attacks.FdiInjector]
        C[Controlador PID<br/>control.ControllerClient]
    end
    subgraph Análisis
        M[Monitor OPC UA<br/>detection.OnlineMonitor]
        D1[Detector causal]
        D2[Método base]
        H[(Historiador)]
    end
    UI[HMI web NiceGUI :8080]
    PS <-->|OPC UA SignAndEncrypt| GW
    GW <-->|OPC UA| C
    GW -->|OPC UA| M
    M --> D1 & D2
    D1 & D2 --> H --> UI
    O[Orquestador / CLI] -.->|plano de experimento| P
    O -.-> GW & C & M & H
```

| Componente | Proceso | Endpoint | Paquete |
|---|---|---|---|
| Servidor de planta + planta | `plant_server` | `opc.tcp://127.0.0.1:4840/fdisim/planta` | `opcua.plant_server`, `process` |
| Gateway agregador + inyector | `gateway` | `opc.tcp://127.0.0.1:4841/fdisim/gateway` | `opcua.gateway`, `attacks` |
| Controlador PID | `controller` | cliente del gateway | `control` |
| Monitor + detectores | `monitor` o embebido en la HMI | cliente del gateway | `detection` |
| HMI | `ui` | `http://127.0.0.1:8080` | `ui` |
| Orquestador | proceso principal (CLI) | — | `orchestration`, `cli` |

## Secuencia de un paso de co-simulación

```mermaid
sequenceDiagram
    participant CK as Reloj (Δt)
    participant PL as Planta
    participant PS as Servidor de planta
    participant GW as Gateway (inyector)
    participant CT as Controlador PID
    participant MO as Monitor/detectores
    CK->>PL: paso t → t+Δt con u vigente
    PL->>PS: mediciones (LT-101, LT-102, FT-101)
    PL-->>MO: verdad de terreno (plano de experimento, solo para evaluación)
    PS->>GW: notificación de suscripción
    GW->>GW: observe() + falsify() si hay ataque activo
    GW->>CT: valores (posiblemente falsos)
    GW->>MO: los mismos valores
    CT->>GW: escribe P-101
    GW->>PS: reenvía P-101
    MO->>MO: residuos causales, CUSUM/EWMA, umbrales base
```

## Contratos de datos

Definidos en `src/fdisim/common/types.py`: `Sample`, `GroundTruthRecord`, `AttackSpec`, `StealthSpec`, `AttackEvent`, `Alarm`, `RunManifest`. Son la interfaz estable entre módulos; cambiarlos exige acuerdo del equipo y actualizar las pruebas.

## Decisiones tecnológicas

Justificación completa en el Informe OE1 (§7): Python 3.12, asyncua, NumPy/SciPy, tigramite (PCMCI), statsmodels (Granger), scikit-learn, networkx, pandas/pyarrow y **NiceGUI** como HMI web local. NiceGUI se eligió frente a una ventana Tk porque corre sobre el mismo bucle asyncio que asyncua y envía las actualizaciones al navegador por websockets.
