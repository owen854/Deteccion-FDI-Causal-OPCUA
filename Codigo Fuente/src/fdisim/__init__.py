"""FDISim-OPCUA: marco de simulación para la detección de inyección de datos falsos (FDI)
en redes OPC UA mediante análisis causal.

Proyecto de semillero SIDDFAI — Universidad de Pamplona.

Subpaquetes (módulos de la ERS, Documento 01):

- ``common``         contratos de datos, configuración, reloj y plano de experimento.
- ``process``        M1  planta de dos tanques (SciPy).
- ``control``        M2  controlador PID como cliente OPC UA.
- ``opcua``          M3  modelo de información, seguridad, servidor de planta y gateway.
- ``attacks``        M4  motor de inyección FDI (sesgo, rampa, replay).
- ``data``           M5  historiador y datasets reproducibles.
- ``causal``         M6  grafo físico, descubrimiento causal y SCM.
- ``detection``      M7–M8 detector causal y método base de umbrales.
- ``evaluation``     M9  métricas, campañas y reportes.
- ``orchestration``  M11 orquestador y modos en red/offline.
- ``ui``             M10 HMI web (NiceGUI).

Estado: Fase 0 (arquitectura). Las funciones pendientes lanzan ``NotImplementedError``
indicando la fase del Plan de Gestión (Documento 03) en la que se implementan.
"""

__version__ = "0.1.0"
