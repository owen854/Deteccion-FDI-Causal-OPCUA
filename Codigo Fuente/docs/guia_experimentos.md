# Guía de experimentos: ataques FDI, escenarios y datasets (Fase 4)

Requerimientos: RF-16 a RF-27, RF-38, RF-48; RNF-04, RNF-08. Los comandos se ejecutan desde `Codigo Fuente/` con el entorno virtual activo. La evaluación comparativa (campañas, métricas y estadística) se completa en la Fase 8.

## 1. El ataque y dónde ocurre

El atacante controla el **gateway agregador**, un nodo autorizado de la red. Tiene sus certificados y credenciales legítimos, así que todo lo que publica viaja firmado y cifrado (SignAndEncrypt) con StatusCode `Good`. Ninguna verificación del protocolo lo delata (Informe OE1 §3.6). El motor de inyección (`attacks/injector.py`) se instala en ese gateway:

- **Mediciones** (LT-101, LT-102, FT-101): se falsifican en el camino planta → clientes. Por eso el controlador, el monitor y la HMI reciben el mismo dato falso.
- **Órdenes** (P-101, consigna): se falsifican en el camino clientes → planta (RF-24). Mientras dura el ataque, el gateway sigue mostrando a los clientes la orden que escribieron: la manipulación del actuador queda oculta.

Fuera de la ventana de ataque, el gateway es transparente (RF-16).

El modo **offline** aplica la misma clase `FdiInjector` en el mismo lugar de la cadena (planta → inyector → controlador y monitor; controlador → inyector → planta), sin red y sin reloj de pared (RF-38).

## 2. Tipos de ataque (RF-17 a RF-19)

| Tipo | Valor recibido | Parámetros |
|---|---|---|
| `bias` (sesgo) | yₐ = y + b | `bias` (b) |
| `ramp` (rampa) | yₐ = y + r·(t − tₛ), con \|r·(t − tₛ)\| ≤ Δ_max | `slope_per_s` (r), `max_deviation` (Δ_max, opcional) |
| `replay` (repetición) | Repite en bucle los valores legítimos de [tₛ − T_rec, tₛ) | `record_s` (T_rec) |

**Sigilo (RF-20).** Sea δ = yₐ − y la desviación inyectada. Con `stealth.enabled`:

- **Tasa limitada:** δ cambia como máximo `max_rate_per_s`·Δt por paso. Se limita la desviación, no el valor publicado. Así la señal falsa conserva el ruido natural del sensor: limitar el valor recortaría también ese ruido y la señal quedaría delatoramente suave.
- **Salida gradual:** \|δ\| ≤ ρ·(tₑ − t). El ataque vuelve a cero dentro de su ventana, sin escalón al final.
- **Envolvente:** yₐ se satura en `envelope` = [y_min, y_max].

Con ρ = 0,5 cm/s, un sesgo de 2 cm tarda 4 s en entrar y 4 s en salir.

**Ataques coordinados y sobre el actuador (RF-24).** Un escenario puede declarar varios ataques a la vez, sobre variables distintas o sobre la misma; en la misma variable se aplican en orden. Un ataque sobre `P-101` altera la orden que llega a la bomba.

## 3. Catálogo de escenarios (RF-22)

Todos heredan de `normal.yaml`: 1800 s, cambios de consigna y perturbaciones legítimas.

| Escenario | Ataque | Ventana |
|---|---|---|
| `normal.yaml` | — (entrenamiento, validación y falsos positivos) | — |
| `sesgo_lt102.yaml` | +2 cm en LT-102, con sigilo | 900–1200 s |
| `rampa_lt102.yaml` | 0,01 cm/s en LT-102, máximo 5 cm | 900–1500 s |
| `replay_lt102.yaml` | Repite 120 s de LT-102; la consigna cambia durante el ataque | 900–1300 s |
| `sesgo_lt101.yaml` | +1,5 cm en LT-101 | 900–1200 s |
| `rampa_lt101.yaml` | 0,008 cm/s en LT-101, máximo 4 cm | 900–1500 s |
| `replay_lt101.yaml` | Repite 120 s de LT-101; la consigna cambia durante el ataque | 900–1300 s |
| `coordinado_lt101_lt102.yaml` | +1 cm en LT-101 y +2 cm en LT-102 a la vez (RF-24) | 900–1200 s |
| `actuador_p101.yaml` | +8 % en la orden de la bomba, oculto a los clientes (RF-24) | 900–1200 s |

Campos de un ataque:

```yaml
attacks:
  - id: A1
    type: bias            # bias | ramp | replay
    targets: [LT-102]     # una o varias: LT-101, LT-102, FT-101, P-101, LIC-102.SP
    start_s: 900
    duration_s: 300
    params: { bias: 2.0 } # ramp: slope_per_s, max_deviation · replay: record_s
    stealth: { enabled: true, envelope: [2.0, 45.0], max_rate_per_s: 0.5 }
```

## 4. Ejecutar escenarios

En red, con los procesos OPC UA reales. `--escala 5` corre a 5× el tiempo real (RNF-04):

```bash
fdisim run --scenario config/scenarios/sesgo_lt102.yaml --escala 5
```

En modo offline, sin red, determinista y unas 590× más rápido que el tiempo real:

```bash
fdisim run --mode offline --scenario config/scenarios/sesgo_lt102.yaml
```

Al final de cada corrida la CLI imprime el efecto medido de cada ataque y los criterios de aceptación:

- **Sesgo:** diferencia mediana entre lo recibido y lo medido por el sensor.
- **Rampa:** pendiente y R².
- **Replay:** porcentaje de valores repetidos.
- **Siempre:** transparencia fuera de la ventana, StatusCode `Good`, envolvente respetada y retardo del primer valor falso.

## 5. Etiquetas (RF-21)

El gateway publica por el plano de experimento un `AttackEvent` cuando cada ataque empieza y cuando termina. Al cerrar la corrida, el orquestador guarda estos datos:

- `attacks.parquet`: un intervalo por ataque (id, tipo, objetivos, inicio, fin y parámetros).
- `samples.parquet`: agrega `sim_time` y tres columnas de etiqueta:
  - `label`: 1 si hay algún ataque activo;
  - `attack_id`;
  - `tag_attacked`: 1 si esa variable es la atacada.
- `ground_truth.parquet`: `attack_active` y `attack_id` en cada paso.

Las etiquetas se derivan del intervalo ejecutado, no de los datos. Coinciden con la programación del escenario, o con el clic en la HMI, al paso de simulación.

**Tiempo simulado canónico.** La planta usa round(k·Δt, 6) y el gateway calcula el tiempo de cada muestra a partir de su SourceTimestamp, redondeado al milisegundo. Así ambos lados ven exactamente los mismos bordes de ventana.

## 6. Ataques interactivos desde la HMI (RF-23, RF-48)

```bash
fdisim run --scenario config/scenarios/normal.yaml --escala 2 --ui
```

En la página **Experimentos** (`http://127.0.0.1:8080/experimentos`) se elige el tipo, la variable objetivo, los parámetros, la duración y el sigilo, y se pulsa **Armar ahora**. El ataque empieza en el tiempo simulado actual, menos de 1 s después del clic. La tabla muestra los ataques del escenario y los armados, con su estado (programado, activo o terminado), y permite desarmarlos.

La orden no viaja por OPC UA. La HMI la envía al orquestador por un canal local (127.0.0.1) autenticado con una clave aleatoria por corrida, y el orquestador la reenvía al gateway por el plano de experimento. Un replay armado en caliente usa el historial reciente del gateway como grabación.

## 7. Datasets v1 (RF-27)

```bash
fdisim dataset --out data/processed/v1
```

Genera por lotes (Monte Carlo) corridas offline con semillas controladas y luego tres tablas:

- `train.parquet`: 10 corridas normales.
- `val.parquet`: 3 corridas normales.
- `test.parquet`: 3 corridas normales y 2 por cada uno de los 8 escenarios de ataque.

Las opciones `--entrenamiento`, `--validacion`, `--prueba`, `--por-ataque`, `--semilla` y `--ataques` cambian esos valores.

- **Formato:** rejilla de 0,5 s (`detection.period_s`) con retención de orden cero. Columnas: `run_id`, `scenario`, `seed`, `sim_time`, las cinco variables, `label`, `attack_id` y `atk_<variable>`.
- **Sin solapamiento temporal:** cada corrida es una serie independiente con semilla propia y va completa a una sola partición.
- **Semillas:** las normales usan `base_seed + i`; el escenario de ataque *j* usa `base_seed + 1000·(j+1) + i`.
- **Reproducibilidad:** el modo offline no usa el reloj de pared, así que la misma semilla produce archivos idénticos (SHA-256 iguales; prueba automática `test_datasets_v1_reproducibles_y_sin_solapamiento`).
- **Manifiesto:** `dataset_manifest.json` guarda semillas, corridas, particiones, tamaños, commit, versiones y el SHA-256 de cada tabla. Las corridas quedan en `runs/`, cada una con su propio manifiesto.

`data/` no se versiona; el dataset se regenera con el comando anterior.

## 8. Flujo experimental de las fases siguientes

1. `fdisim dataset` → `data/processed/v1/` (Fase 4).
2. `fdisim train --data data/processed/v1/train.parquet` → modelo causal (Fase 5).
3. Detector causal y método base sobre `test.parquet` y en línea (Fase 6).
4. `fdisim campaign --campaign config/campaigns/campana_oe4.yaml` y `fdisim report` (Fase 8).

## 9. Resultados de referencia (18/11/2026)

Modo offline: las corridas `<escenario>_s<semilla>` del dataset v1, con la primera semilla de cada escenario.

| Escenario | Efecto medido | Criterios |
|---|---|---|
| `sesgo_lt102` | diferencia mediana +2,000 cm | 8/8 |
| `rampa_lt102` | pendiente 0,0100 cm/s, R² = 1,000 | 8/8 |
| `replay_lt102` | 100 % de los valores repetidos | 6/6 |
| `sesgo_lt101` | +1,500 cm | 8/8 |
| `rampa_lt101` | 0,0080 cm/s, R² = 1,000 | 8/8 |
| `replay_lt101` | 100 % repetido | 6/6 |
| `coordinado_lt101_lt102` | +2,000 cm (LT-102) y +1,000 cm (LT-101) | 8/8 |
| `actuador_p101` | la bomba recibe +8,0 % sobre la orden escrita | 5/5 |

Velocidad offline: entre 576× y 603× el tiempo real (RNF-04 pide ≥ 100×). Dataset v1: 36 010 filas de entrenamiento, 10 803 de validación y 68 419 de prueba, de las cuales 12 800 están bajo ataque.

El ruido se conserva bajo ataque: la desviación estándar entre pasos de la señal recibida es igual a la del sensor (0,1433 frente a 0,1433 cm en `sesgo_lt102`).

**Modo en red (hito H3).** Los tres ataques sobre LT-102 corrieron con los cuatro procesos OPC UA reales, SignAndEncrypt / Basic256Sha256, a **5× el tiempo real** (1800 s simulados en 6 min). Las corridas son `20261118-212701_sesgo_lt102`, `20261118-213319_rampa_lt102` y `20261118-213937_replay_lt102`.

| Escenario | Efecto recibido por el monitor | Lazo en red frente al offline (IAE por cambio de consigna) | Latencia p95 | Criterios |
|---|---|---|---|---|
| `sesgo_lt102` | +2,000 cm, 3000 valores falsos | 931,3 / 926,4 y 515,1 / 514,1 (≤ 0,6 %) | 117 ms | 12/12 |
| `rampa_lt102` | 0,0100 cm/s, R² = 1,000, 6000 valores falsos | 755,3 / 751,5 y 1322,7 / 1321,2 (≤ 0,5 %) | 121 ms | 12/12 |
| `replay_lt102` | 100 % de la ventana repetido, 4000 valores falsos | 2073,6 / 2077,6 y 260,6 / 262,7 (≤ 0,8 %) | 128 ms | 10/10 |

En las tres:

- Completitud del 100 % y gateway transparente fuera de los ataques.
- Todos los valores falsos llegaron con StatusCode `Good` y dentro de la envolvente.
- El primer valor falso llegó en el primer paso de la ventana.
- Deriva del reloj ≤ 0,007 %.
- 0 ciclos del controlador sin datos y 0 escrituras fallidas.

El lazo en red reproduce al offline con diferencias de IAE menores al 1 %, así que la co-simulación a 5× no degrada el control (RNF-04). En `rampa_lt102` hubo 11 pasos atrasados de 18 000: con pasos de 20 ms de reloj, eso no afectó la deriva ni el lazo.

Ataque interactivo desde la HMI (RF-23): en una corrida de `normal` a 2×, un sesgo de +2 cm sobre LT-102 se armó en t = 40,1 s y se desarmó en t = 140,8 s. Ambos instantes quedaron registrados como el intervalo del ataque. Las capturas están en [evidencias/fase4/](evidencias/fase4/).
