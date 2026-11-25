# Guía del modelo causal de referencia (Fase 5)

Requerimientos: RF-28 a RF-32 (OE3). El análisis completo y su discusión están en el **Documento 05 — Estudio comparativo del modelo causal** (`Documentacion/`). Los comandos se ejecutan desde `Codigo Fuente/` con el entorno virtual activo.

## 1. Entrenar

```bash
fdisim dataset --out data/processed/v1
```

```bash
fdisim train --data data/processed/v1/train.parquet
```

`train` usa `val.parquet` de la misma carpeta para validar. Tarda unos 80 s con el análisis de sensibilidad; `--sin-sensibilidad` lo omite. Opciones: `--tau-max` (3), `--alpha` (0,01), `--bloque` (10 muestras = 5 s en la resolución agregada) y `--out` (`data/models/causal_v1`).

El flujo:

1. **Grafo físico a priori (RF-28).** 8 enlaces derivados de los balances de masa y de la ley de control (`causal/prior_graph.py`).
2. **Descubrimiento (RF-29).** PCMCI+ (tigramite, ParCorr, con la consigna declarada exógena) y Granger condicional (statsmodels, VAR por mínimos cuadrados), en dos resoluciones:
   - la rejilla de detección de 0,5 s;
   - promedios por bloques de 5 s, que reducen el ruido de medición.
3. **Sensibilidad.** Ambos métodos con τ_max ∈ {1, 2, 3, 5}, α ∈ {0,001; 0,01; 0,05} y las dos resoluciones: 48 configuraciones.
4. **Comparación y consolidación (RF-30).** Mide SHD, precisión y exhaustividad (con y sin retardo) frente al grafo físico. Arma el grafo de referencia con decisiones justificadas y clasifica cada discrepancia con su causa probable.
5. **SCM (RF-31).**
   - Físico-informado: balances de masa con a1 y a2, bomba de primer orden (k_p, τ) y PI incremental (Kc, Ki) identificados por mínimos cuadrados.
   - Alternativa por regresión lineal sobre los padres del grafo de referencia.
   - Estadísticas de los residuos a un paso.
6. **Persistencia (RF-32).** Modelo, grafo, residuos y umbrales iniciales (3σ), con un manifiesto que incluye el SHA-256 del dataset de origen y de cada archivo.

## 2. Qué queda en `data/models/causal_v1/`

| Archivo | Contenido |
|---|---|
| `graph.graphml`, `graph.json` | Grafo de referencia consolidado (enlaces con retardo y justificación) |
| `graph_physical.graphml` | Grafo físico a priori |
| `scm.json` | SCM físico-informado: ecuaciones y parámetros identificados |
| `scm_regression.json` | SCM alternativo por regresión |
| `residual_stats.json` | Media y desviación de los residuos a un paso (datos normales) |
| `thresholds.json` | Umbrales iniciales 3σ por variable (la Fase 6 los calibra) |
| `report.md`, `report.json` | Reporte comparativo: enlaces por método, métricas, sensibilidad, consolidación, parámetros y RMSE |
| `figures/` | Grafo de referencia y residuos en validación |
| `manifest.json` | Dataset de origen y sus SHA-256, configuración, métricas, criterios, versiones y SHA-256 de cada archivo |

Uso desde código:

```python
from fdisim.causal.model_store import load_model

model, graph, thresholds = load_model("data/models/causal_v1")  # verifica los SHA-256
residuals = model.residuals(frame)  # frame: rejilla con run_id, sim_time y las 5 variables
```

## 3. Grafo de referencia (rejilla de 0,5 s)

| Variable | Padres (retardo en pasos de 0,5 s) |
|---|---|
| LT-101 | LT-101 (1), FT-101 (1) |
| LT-102 | LT-102 (1), LT-101 (1) |
| FT-101 | P-101 (1, 2, 3): bomba de primer orden, τ = 0,5 s |
| P-101 | P-101 (1), LIC-102.SP (0, 1), LT-102 (0, 1): PI en forma incremental |

Cambios respecto del grafo físico:

- P-101 → FT-101 pasa de contemporáneo a retardos 1 a 3. La orden escrita en *t* se aplica durante (t, t+0,5 s] y la bomba tiene inercia.
- Se agregan LT-102 y la consigna con retardo 1 sobre P-101: el PI incremental depende del error anterior.

## 4. Resultados de referencia (19/11/2026, dataset v1)

**Parámetros identificados**: todos dentro de ±1 % de los nominales (RF-31 pide ±10 %).

| Parámetro | Identificado | Nominal | Error |
|---|---|---|---|
| a1 [cm²] | 0,5009 | 0,5 | +0,18 % |
| a2 [cm²] | 0,4039 | 0,4 | +0,96 % |
| k_p [cm³/s por %] | 1,5001 | 1,5 | +0,01 % |
| τ bomba [s] | 0,5005 | 0,5 | +0,11 % |
| Kc | 2,4995 | 2,5 | −0,02 % |
| Ki [1/s] | 0,014997 | 0,015 | −0,02 % |

**RMSE a un paso en validación** (RF-31 pide ≤ 2σ del sensor):

| Variable | Físico-informado | Regresión | Límite 2σ |
|---|---|---|---|
| LT-101 | 0,141 cm | 0,141 cm | 0,20 cm |
| LT-102 | 0,141 cm | 0,141 cm | 0,20 cm |
| FT-101 | 0,502 cm³/s | 0,504 cm³/s | 1,00 cm³/s |
| P-101 | 0,007 % | 0,007 % | — |

Los RMSE de los niveles coinciden con √2·σ del sensor: el modelo explica toda la dinámica, y lo que queda es el ruido de las dos mediciones que intervienen en cada predicción.

**Descubrimiento frente al grafo físico** (configuración principal: τ_max = 3, α = 0,01):

| Método | Enlaces | SHD | Precisión sin retardo | Exhaustividad sin retardo |
|---|---|---|---|---|
| PCMCI+ 0,5 s | 17 | 15 | 0,78 | 0,88 |
| Granger 0,5 s | 35 | 37 | 0,42 | 1,00 |
| PCMCI+ 5 s | 10 | 8 | 0,71 | 0,62 |
| Granger 5 s | 12 | 16 | 0,45 | 0,62 |

PCMCI+ es más preciso. Granger encuentra casi todos los pares pero sobre-conecta el lazo cerrado. Agregar a 5 s reduce los enlaces espurios a costa de exhaustividad.

## 5. Implicación para el detector (Fase 6)

Con el dataset de prueba, la media del residuo a un paso dentro de la ventana de ataque, en unidades de σ, se separa claramente en varios casos:

- **Ataque al actuador:** +23,6σ en FT-101.
- **Sesgo sobre LT-101:** −0,15σ sostenido en LT-102. Acumulado en la ventana equivale a −3,7σ.
- **Replay sobre LT-102:** −0,26σ, equivalente a −7,2σ acumulado.

En cambio, un sesgo sigiloso sobre LT-102 apenas mueve el residuo (+0,01σ). La predicción a un paso usa el mismo nivel falsificado, que el integrador «absorbe». Por eso la Fase 6 combina tres herramientas:

- residuos en horizonte H (gemelo causal que no usa la medición atacada, RF-33);
- acumulación con CUSUM/EWMA (RF-34);
- firmas cruzadas entre variables para identificar la atacada (RF-37).

Figuras del estudio en [evidencias/fase5/](evidencias/fase5/): grafo de referencia, residuos en validación, sensibilidad del SHD y evidencia acumulada de los residuos bajo ataque.
