# Guía de experimentos (borrador)

Se completa en las Fases 4 y 8. Requerimientos: RF-20 a RF-22, RF-27, RF-41 a RF-46.

## 1. Escenarios

Un escenario (`config/scenarios/*.yaml`) define la duración, la semilla, el perfil de consigna, las perturbaciones legítimas y los ataques. Puede heredar de otro con `base:`.

| Escenario | Propósito |
|---|---|
| `normal.yaml` | Datos de entrenamiento y validación; medición de falsos positivos |
| `sesgo_lt102.yaml` | Sesgo de +2 cm en LT-102 entre 900 s y 1200 s |
| `rampa_lt102.yaml` | Deriva de 0,01 cm/s en LT-102 (máximo 5 cm) |
| `replay_lt102.yaml` | Reproducción de 120 s grabados, con cambio de consigna durante el ataque |

Campos de un ataque:

```yaml
attacks:
  - id: A1
    type: bias            # bias | ramp | replay
    targets: [LT-102]
    start_s: 900
    duration_s: 300
    params: { bias: 2.0 } # ramp: slope_per_s, max_deviation · replay: record_s
    stealth: { enabled: true, envelope: [2.0, 45.0], max_rate_per_s: 0.5 }
```

## 2. Flujo experimental

1. Generar datos normales (offline, varias semillas) → `data/raw/`.
2. Construir particiones de entrenamiento y validación → `data/processed/`.
3. `fdisim train` → modelo causal en `data/models/causal_v1/`.
4. `fdisim campaign --campaign config/campaigns/campana_oe4.yaml`.
5. `fdisim report --campaign-dir results/campana_oe4`.
6. Subconjunto en red (`network_subset`) para medir latencia y tiempo de respuesta.

## 3. Diseño del experimento (OE4)

- **Factores:** tipo de ataque, variable objetivo, magnitud (barridos de `sweeps`), sigilo.
- **Respuestas:** DR, FPR, falsas alarmas por hora, retardo, precisión, exhaustividad, F1, AUC, tiempo de procesamiento, latencia OPC UA, tiempo de respuesta.
- **Repeticiones:** 30 por condición, con semillas `base_seed + i`.
- **Comparación:** detector causal vs. método base sobre las mismas muestras; prueba de Wilcoxon pareada, α = 0,05.

## 4. Reproducibilidad

Cada corrida guarda `manifest.json` con la semilla, el commit, las versiones de las dependencias y el SHA-256 de cada archivo. En modo offline, la misma semilla debe producir archivos idénticos (RNF-08).
