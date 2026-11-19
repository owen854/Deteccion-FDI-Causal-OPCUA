# Guía de la co-simulación en red (Fase 3)

Cómo ejecutar la planta, el gateway, el controlador y el monitor como procesos OPC UA independientes, qué queda guardado de cada corrida y cómo verificarla.
Requerimientos: RF-05, RF-06, RF-08, RF-09, RF-10 a RF-15, RF-25, RF-26, RF-47 (básico), RF-53 a RF-55; RNF-01, RNF-03, RNF-07, RNF-09 a RNF-12.
Todos los comandos se ejecutan desde `Codigo Fuente/` con el entorno virtual activo.

## 1. Preparar la PKI

```bash
fdisim certs
```

Crea lo que falte en `certs/` (no versionado): un certificado por componente, las listas de confianza y `credenciales.json`. Es equivalente a `python scripts/generar_certificados.py`. Para verificar con UaExpert, agregue su certificado a la planta y al gateway (abra UaExpert al menos una vez antes):

```bash
fdisim certs --confiar-uaexpert
```

## 2. Ejecutar un escenario

Corrida completa del escenario `normal` (30 min en tiempo real, hito H2):

```bash
fdisim run --scenario config/scenarios/normal.yaml
```

Prueba rápida de 2 minutos simulados a 2× (1 min de reloj):

```bash
fdisim run --scenario config/scenarios/normal.yaml --duracion 120 --escala 2
```

Con la HMI abierta en `http://127.0.0.1:8080`:

```bash
fdisim run --scenario config/scenarios/normal.yaml --ui
```

Opciones: `--seed` (semilla), `--duracion` (segundos simulados), `--escala` (1 = tiempo real) y `--config` (un YAML propio con solo las claves que cambian; el resto se toma de `config/default.yaml`).

Qué ocurre:

1. El orquestador valida la configuración (un error indica el campo, p. ej. `opcua.gateway.port`).
2. Lanza en orden planta (4840) → gateway (4841) → controlador → monitor. Cada uno se conecta con SignAndEncrypt, su certificado y su usuario, y avisa que está listo.
3. Da la orden de inicio a la planta. El reloj avanza con Δt = 0,1 s, la planta aplica el comando P-101 que escribió el controlador, publica las mediciones y envía la verdad de terreno por el plano de experimento.
4. El gateway retransmite cada valor a sus clientes y reenvía a la planta las escrituras de P-101 y de la consigna. El controlador ejecuta el PI cada 0,5 s y el monitor registra cada muestra.
5. Al terminar (o con Ctrl+C) detiene los procesos en orden inverso y guarda la corrida.

## 3. Qué queda guardado

```
data/raw/<run_id>/
├── samples.parquet        muestras recibidas por el monitor: valor, SourceTimestamp,
│                          ServerTimestamp, tiempo de recepción y StatusCode (RF-14)
├── ground_truth.parquet   un registro por paso: valores reales y medidos (RF-06)
├── config.yaml            configuración efectiva completa
├── scenario.yaml          escenario resuelto (semilla y duración incluidas)
├── summary.json           indicadores y criterios de aceptación de la corrida
└── manifest.json          semilla, commit, versiones y SHA-256 de cada archivo (RF-26)
logs/<run_id>/             una bitácora por componente: orchestrator, plant_server,
                           gateway, controller, monitor (y hmi) (RF-55)
```

`summary.json` incluye:

- **Completitud:** pasos que llegaron al monitor frente a los publicados.
- **Transparencia del gateway:** muestras que difieren de lo que publicó la planta.
- **Latencias por salto:** planta → gateway, gateway → monitor y extremo a extremo.
- **Reloj:** pasos atrasados y deriva; también el tiempo de cómputo por paso.
- **Control:**
  - error de seguimiento por tramo de consigna;
  - desempeño en cada cambio de consigna, comparado con el mismo escenario en modo offline;
  - reconexiones de cada cliente.
- **Criterios de aceptación de la fase,** marcados como cumplidos o no.

La CLI los imprime al final de cada corrida. Para verificar que una corrida no fue alterada:

```bash
python -c "from fdisim.data.storage import verify_run; print(verify_run('data/raw/<run_id>'))"
```

## 4. HMI v0

`fdisim ui` abre la página de operación. También se abre con `fdisim run --ui`. La HMI es un cliente OPC UA más del gateway, con su propia identidad (`hmi`): muestra exactamente lo que publica el gateway.

- **Encabezado:** estado de la conexión, tiempo simulado, estado de la simulación y seguridad del canal.
- **Sinóptico:** bomba → tanque 1 → tanque 2 → descarga, con niveles, caudal, comando de la bomba y la consigna como línea roja discontinua.
- **Consigna (RF-09):** el valor llega a la planta en menos de 1 s. Se mantiene hasta el siguiente cambio programado del escenario.
- **Tendencias:** últimos 10 min de niveles y consigna, comando de la bomba y caudal.

Si no hay una corrida activa, la HMI indica «Sin conexión» y sigue intentando conectarse.

## 5. Verificación con UaExpert sobre el gateway (opcional)

Con una corrida en marcha y el certificado de UaExpert agregado (sección 1):

1. En UaExpert, use *Server → Add* con estos datos:
   - URL: `opc.tcp://127.0.0.1:4841/fdisim/gateway`
   - política **Basic256Sha256** y modo **Sign & Encrypt**
   - usuario `uaexpert` y la contraseña de `certs/credenciales.json`
2. Acepte el certificado `FDISim-OPCUA gateway`.
3. Arrastre `Tanque1/Nivel`, `Tanque2/Nivel`, `Bomba/Comando` y `Control/Consigna` al *Data Access View*.

A diferencia de la Fase 1, ahora los valores son los de la simulación física. El comando de la bomba cambia cada 0,5 s porque lo escribe el controlador, y la consigna cambia en t = 600 s y t = 1200 s del escenario `normal`.

## 6. Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `No se inició la corrida: El puerto 4840 … ya está en uso` | Otra corrida o el servidor de la prueba de concepto (`poc_opcua_segura.py --servir`) ocupa el puerto. Deténgalo con Ctrl+C, o use otros puertos con un YAML propio (abajo). |
| `Faltan certificados de '…'` | Ejecute `fdisim certs`. |
| La HMI muestra «Sin conexión» | No hay una corrida activa, o la HMI usa otra configuración de puertos que la corrida: inicie ambas con el mismo `--config`. |
| `opcua.host: solo se permite localhost …` | RNF-11: los endpoints solo se ligan a localhost o a una red privada de laboratorio. |

YAML propio con otros puertos (las demás claves se toman de `default.yaml`):

```yaml
opcua:
  plant_server: { port: 4850 }
  gateway: { port: 4851 }
```

```bash
fdisim run --scenario config/scenarios/normal.yaml --config mis_puertos.yaml
```

**Latencia.** El gateway se suscribe a la planta cada 20 ms (`opcua.subscription.gateway_publishing_interval_ms`), mientras que sus clientes usan el intervalo configurado de 100 ms. Si ambos saltos usaran 100 ms, la latencia de punta a punta dependería del desfase entre los dos ciclos de publicación, que queda fijo al arrancar. En una corrida de 30 min con 100 ms en ambos saltos se midió un p95 de 196 ms, al límite de RNF-03.

## 7. Pruebas automáticas

```bash
pytest tests/integration/test_cosimulacion_opcua.py tests/integration/test_closed_loop.py tests/integration/test_opcua_roundtrip.py
```

Verifican, con una PKI temporal y puertos libres:

- la ida y vuelta de lectura, escritura y suscripción;
- el lazo cerrado con gateway transparente, sin muestras perdidas;
- el cambio de consigna en menos de 1 s;
- la reconexión de los clientes en menos de 5 s tras reiniciar el gateway;
- una corrida corta con procesos reales, su manifiesto y sus bitácoras.

## 8. Resultados de referencia (hito H2)

Corrida `20261118-195349_normal` del 18/11/2026:

- **Escenario:** `normal`, 1800 s simulados a 1× (30 min de reloj), semilla 1.
- **Seguridad:** SignAndEncrypt con Basic256Sha256 y usuario en todos los enlaces.
- **Puertos:** 4850/4851, porque 4840 estaba ocupado.
- **Componentes:** planta, gateway, controlador y monitor como procesos separados, más la HMI conectada.

| Indicador | Resultado | Criterio |
|---|---|---|
| Verdad de terreno | 18 000 / 18 000 pasos | RF-06: 100 % |
| Completitud en el monitor (LT-101, LT-102, FT-101) | 18 000 / 18 000 en cada una (100 %) | RF-25: ≥ 99,9 % |
| Transparencia del gateway | 54 000 muestras comparadas, 0 diferencias | RF-13 |
| Latencia planta → gateway | p50 15 ms, p95 31 ms | — |
| Latencia gateway → monitor | p50 48 ms, p95 71 ms | — |
| Latencia extremo a extremo | p50 65 ms, **p95 78 ms**; un caso aislado de 1,0 s | RNF-03: p95 ≤ 200 ms |
| Latencia añadida por el gateway | p50 1,7 ms, p95 3,0 ms | RF-13: registrada |
| Reloj de co-simulación | 0 pasos atrasados, atraso medio 2,9 ms, deriva 0,0007 % | RF-05: < 1 % |
| Cómputo por paso | media 0,73 ms, p99 1,35 ms | RNF-01: < 10 ms |
| Controlador | 3 599 ciclos, 0 sin datos, 0 escrituras fallidas; el gateway reenvió las 3 599 | RF-08 |
| Seguimiento en el tramo sin perturbación (25 cm) | error 0,06 % | RF-08: < 2 % |
| Lazo en red frente al offline | IAE 817,0 frente a 815,1 (escalón a 30 cm) y 643,6 frente a 639,8 (a 22 cm): diferencias de 0,2 % y 0,6 % | ± 5 % |
| Reconexiones durante la corrida | 0 | — |
| Reconexión tras reiniciar el gateway | ≤ 5 s (prueba automática) | RF-15, RNF-07 |
| Manifiesto | 5 archivos con SHA-256 verificados | RF-26 |

Notas:

- **Tramos de 30 y 22 cm.** Su error (4,4 % y 0,9 %) lo causan las perturbaciones legítimas del escenario: el cambio en la salida del tanque 2 en t = 900–1020 s y la fuga del tanque 1 en t = 1500–1560 s. La simulación offline con la misma semilla da los mismos valores. Por eso esos tramos se marcan como perturbados y no cuentan para RF-08.
- **Latencia.** Con 100 ms en ambos saltos, la latencia de punta a punta fue de p50 184 ms y p95 196 ms en otra corrida de 30 min. Con el enlace interno de 20 ms bajó a p95 78 ms (sección 6).
- **Commit en el manifiesto.** Como la corrida se hizo antes de confirmar los cambios, el manifiesto registra el commit base con el sufijo `-dirty`.

Evidencias en [evidencias/fase3/](evidencias/fase3/): `hmi_operacion_cambio_consigna.jpg` muestra el escalón a 30 cm visto en la HMI y `hmi_fin_corrida_consigna_22.jpg`, el final de la corrida, ya establecida en 22 cm.
