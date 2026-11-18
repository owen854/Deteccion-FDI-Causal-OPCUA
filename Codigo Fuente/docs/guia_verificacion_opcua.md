# Guía de verificación OPC UA (Fase 1)

Procedimientos para verificar la seguridad y la interoperabilidad de la comunicación OPC UA.
Requerimientos: RF-10, RF-11, RF-12; RNF-09, RNF-10, RNF-12. Todos los comandos se ejecutan desde `Codigo Fuente/` con el entorno virtual activo.

## 1. Generar la PKI local

```bash
python scripts/generar_certificados.py
```

Crea en `certs/` (no versionado) un certificado X.509 por componente, las listas de confianza mínimas y `credenciales.json` con usuarios y contraseñas aleatorias de prueba. Con `--forzar` se regeneran los certificados.

| Componente | Confía en |
|---|---|
| plant_server | gateway |
| gateway | plant_server, controller, monitor, hmi |
| controller, monitor, hmi | gateway |

## 2. Batería automática de seguridad

```bash
python scripts/poc_opcua_segura.py
```

Levanta un servidor con la identidad `plant_server` y el modelo de información real, conecta un cliente con la identidad `gateway` y verifica nueve puntos: endpoints solo seguros, conexión SignAndEncrypt, modelo de información con EURange y EngineeringUnits, niveles de acceso, suscripción con latencia, y el rechazo de un certificado no confiable, de una contraseña incorrecta, de un cliente sin seguridad y de las políticas obsoletas. Para probar otra política use `--politica Aes256_Sha256_RsaPss` o `--politica Aes128_Sha256_RsaOaep`. El reporte queda en `results/fase1/`.

Las mismas comprobaciones se ejecutan en `pytest` (`tests/integration/test_seguridad_opcua.py`).

## 3. Cifrado con Wireshark (automático)

Requiere Wireshark con Npcap y soporte de loopback.

```bash
python scripts/verificar_cifrado.py
```

Captura con `tshark` una sesión idéntica con `SignAndEncrypt` y otra con `None`, y busca en los bytes capturados textos del modelo de información (`PlantaDosTanques`, `Consigna`, `Tanque2`). Resultado esperado: con cifrado no aparecen y los mensajes se ven como *encrypted*; sin cifrado son legibles. Las capturas quedan en `results/fase1/captura_*.pcapng` para abrirlas en Wireshark (filtro `opcua`).

## 4. Interoperabilidad con UaExpert (manual)

1. Abra UaExpert una vez para que cree su propio certificado de aplicación. Al iniciar por primera vez muestra el diálogo *New Application Instance Certificate*: el único campo obligatorio es **Organization** (p. ej. `Universidad de Pamplona`). Deje los valores por defecto (RSA 2048, Sha256) y **no** proteja la clave privada con contraseña.
2. Inicie el servidor de prueba confiando en el certificado de UaExpert:

   ```bash
   python scripts/poc_opcua_segura.py --servir --confiar-uaexpert
   ```

   Si el script indica que no encontró el certificado, exporte el certificado propio de UaExpert (*Settings → Manage Certificates*) en formato DER y cópielo como `certs/plant_server/trusted/uaexpert.der`. Luego reinicie el servidor.
3. En UaExpert: *Server → Add*, pestaña *Advanced*, URL `opc.tcp://127.0.0.1:4840/fdisim/planta`, política **Basic256Sha256**, modo **Sign & Encrypt**, autenticación **Username**: usuario `uaexpert` y la contraseña de `certs/credenciales.json`.
4. Al conectar, UaExpert pedirá confiar en el certificado del servidor (`FDISim-OPCUA plant_server`): acéptelo.
5. Compruebe y registre (los paneles se activan desde el menú *View* si no están visibles):
   - **Address Space:** que aparezca `Objects/PlantaDosTanques` con `Tanque1`, `Tanque2`, `Bomba`, `Control` y `Estado`.
   - **References** (con `Tanque2/Nivel` seleccionado): `HasTypeDefinition → AnalogItemType` y las propiedades `EURange` y `EngineeringUnits`. En **Attributes**, el `Value` de `EURange` muestra el rango [0, 50] y el de `EngineeringUnits`, `cm` (UnitId 4410708, código UNECE `CMT`). `AccessLevel` es `CurrentRead` en los niveles y `CurrentRead, CurrentWrite` en `Control/Consigna`.
   - **Data Access View:** arrastre allí los niveles y la consigna. Los niveles oscilan (≈ 16 y 25 cm) con marcas de tiempo que avanzan; UaExpert muestra las unidades junto al valor (`25 cm`).
   - **Escrituras:** doble clic en la celda *Value*. Escribir en `Control/Consigna` queda registrado en el panel *Log* como `succeeded [ret = Good]`; escribir en `Tanque2/Nivel` debe rechazarse (`BadUserAccessDenied`).
6. Detenga el servidor con Ctrl+C. Registre el resultado (capturas de pantalla) para el Informe del OE1. Al detenerlo, UaExpert registra `ConnectionErrorApiReconnect` y `BadCommunicationError` mientras intenta reconectarse: es esperado.

## 5. Resultados de referencia (18/11/2026)

| Verificación | Resultado |
|---|---|
| Batería de 9 pruebas, políticas Basic256Sha256, Aes128_Sha256_RsaOaep y Aes256_Sha256_RsaPss | 9/9 superadas en las tres |
| Latencia de notificación (publicación 100 ms) | media 73–91 ms; p95 ≈ 110 ms (RNF-03: ≤ 200 ms) |
| Wireshark, SignAndEncrypt | 82 mensajes OPC UA cifrados; ningún texto del modelo legible |
| Wireshark, None (comparación) | 82 mensajes; todos los textos del modelo legibles |
| UaExpert, Basic256Sha256 · Sign & Encrypt · usuario | Conexión aceptada con confianza mutua de certificados; modelo navegable; `AnalogItemType` con `EURange` y `EngineeringUnits` (UaExpert muestra `25 cm`); niveles en vivo; escritura de la consigna `Good` |
| Rechazo de escritura en `Tanque2/Nivel` | Verificado por la batería automática (prueba 4: `BadUserAccessDenied`) |
| Renovación del canal seguro | Canal SignAndEncrypt renovado 5 veces en 12 s (vida de 3 s) sin errores de lectura |

Evidencias de UaExpert en [evidencias/fase1/](evidencias/fase1/): `uaexpert_conexion_modelo.png` (modelo, valores y referencias) y `uaexpert_escritura_consigna.png` (escrituras aceptadas).
