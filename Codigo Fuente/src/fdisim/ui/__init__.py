"""M10 — HMI web local con NiceGUI (RF-47 a RF-52; Informe OE1 §7.6).

La interfaz corre en ``http://127.0.0.1:8080`` sobre el mismo bucle asyncio que los clientes
OPC UA. NiceGUI se importa de forma diferida dentro de las funciones para que el resto del
paquete se pueda usar sin interfaz (campañas headless).
"""
