# Alcance de la versión 1 (primer cierre del proyecto)

El plazo de entrega se adelantó: la versión 1 cierra el proyecto con las **Fases 0 a 7** del Plan de Gestión (Documento 03). Este documento indica qué requerimientos del ERS (Documento 01) quedaron cumplidos y cuáles se difieren, con el criterio usado para decidirlo.

## Criterio de priorización

1. **Se mantienen** todos los requerimientos «Debe» que sostienen la hipótesis del proyecto: simular la planta en lazo cerrado sobre OPC UA seguro, inyectar FDI desde un nodo autorizado, construir el modelo causal y **detectar e identificar** los ataques mejor que un método base. También se mantiene la HMI con la que se demuestra todo lo anterior.
2. **Se difieren** los requerimientos con prioridad «Debería» o «Podría» cuyo aporte ya cubre otra pieza, y los de la Fase 8 (campañas con repeticiones y pruebas estadísticas) y la Fase 9 (manuales completos, informe final y artículo). Son trabajo de análisis y redacción posterior: no cambian el software.
3. Un requerimiento «Debe» diferido conserva una **versión mínima** que deja verificable su objetivo. Por ejemplo, RF-43 se reemplaza por la evaluación sobre el dataset de prueba.

## Requerimientos diferidos (no prioritarios para esta entrega)

| Requerimiento | Prioridad ERS | Decisión | Justificación |
|---|---|---|---|
| RF-35 Consistencia estructural por ventanas | Debería | Diferido (v2) | El gemelo causal en horizonte ya detecta el replay cuando hay excitación (DR 100 % en `replay_lt101` y `replay_lt102`). |
| RF-39 Marca de agua física | Podría | Diferido (v2) | Solo es necesaria para el replay en estado estacionario, un caso fuera del catálogo v1. |
| RF-43 Campañas automatizadas (≥ 30 repeticiones) | Debe (Fase 8) | Versión mínima | `fdisim detect --data` evalúa 16 ataques de 8 escenarios y 3 corridas normales. Falta repetir cada condición 30 veces. |
| RF-44 Comparación causal vs. base | Debe (Fase 8) | Cumplido en versión mínima | Tablas y figuras por escenario en `results/deteccion_v1/`. |
| RF-45 Análisis estadístico (Wilcoxon, IC, curvas de sensibilidad) | Debería | Diferido (Fase 8) | Requiere las campañas con repeticiones. |
| RF-46 Reporte de campaña en HTML | Debe (Fase 8) | Versión mínima | Reporte en Markdown y CSV, con figuras PNG a 300 dpi. Falta el HTML. |
| RF-42 Tiempo de respuesta extremo a extremo (ataque → alarma visible) | Debe | Parcial | Sí se miden el retardo de detección, el tiempo de procesamiento por muestra y la latencia OPC UA. La alarma aparece en la HMI en menos de 1 s (sondeo de 0,25 s), aunque no se mide automáticamente. |
| RF-48 Selección de la política de seguridad desde la HMI | Debe | Parcial | La seguridad es la de la configuración (SignAndEncrypt + Basic256Sha256) y se muestra en todas las páginas. Para cambiarla se edita `config/default.yaml`. |
| RNF-05 Memoria < 2 GB · RNF-06 Operación continua ≥ 2 h | Debería | No verificado | No se hicieron pruebas de resistencia. La corrida más larga es de 30 min (hito H2). |
| RNF-14 Prueba de usabilidad con un integrante | Debería | Pendiente | El aplicativo ya abre con un doble clic (`FDISim.bat`). Falta hacer la prueba. |
| RNF-17 Integración continua (GitHub Actions) | Debe | Pendiente | Se cumplen ruff, las pruebas (233) y la cobertura (83 %), pero se ejecutan a mano. |
| RNF-19 Instalación en Linux · Docker | Debe / opcional | No verificado | La instalación de un comando (`instalar.bat`) solo se verificó en Windows 11. |
| RNF-23 Manual técnico completo, informe final y artículo | Debe (Fase 9) | Parcial | Hay README, guías por fase, manual de usuario y estudios 02 y 05. Falta la redacción final. |

## Requerimientos cumplidos en las Fases 6 y 7

| Requerimiento | Evidencia |
|---|---|
| RF-33 Residuos a un paso y en horizonte (gemelo causal) | `detection/residuals.py`, `PhysicsInformedSCM.simulate`; prueba `test_residuos_*` |
| RF-34 Umbral, CUSUM, EWMA y retención calibrados al FPR objetivo | FPR en validación 0,46 % (objetivo 0,5 %); `test_calibracion_cumple_el_fpr_objetivo` |
| RF-36 Alarmas con todos sus campos y estado | historiador (`alarms`), tabla de la HMI; `test_alarmas_registran_todos_los_campos` |
| RF-37 Identificación de la variable comprometida | 93,8 % de acierto en los ataques detectados; `test_identificacion_por_firmas` |
| RF-38 Mismo detector en línea y fuera de línea | en red, 10 alarmas en línea = 10 al reprocesar (diferencia de 0,0 s); `test_alineador_en_linea_*` |
| RF-40 Método base de umbrales en paralelo | `detection/threshold_detector.py` |
| RF-41 Métricas (DR, FPR, falsas alarmas/h, precisión, exhaustividad, F1, ROC/AUC) | `evaluation/metrics.py`; `test_metrics.py` |
| RF-47 a RF-52 HMI (operación, experimentos, detección, grafo, resultados, comunicaciones) | `ui/pages/*`; capturas en `docs/evidencias/fase7/` |
| RNF-02 Latencia del detector p95 ≤ 50 ms | 0,14 ms fuera de línea y 0,58 ms en red |
| RNF-15 Alarmas visibles ≤ 1 s, colores consistentes | indicador de alarma en el encabezado de todas las páginas |
| RNF-24 Metas indicativas: DR ≥ 90 %, FPR ≤ 2 %, retardo menor que el método base | DR 100 %, FPR 1,0 % en corridas normales, retardo 26,8 s frente a 262,8 s |

## Limitaciones conocidas de la v1

- **FPR en red.** El detector se calibra con corridas offline. En red el ruido de alineación es algo mayor y el FPR medido es más alto (2,7 % en una corrida de 1000 s con el objetivo anterior del 1 %). La mejora natural es calibrar con corridas en red.
- **Perturbaciones legítimas.** El cambio del área de salida del tanque 2 y la fuga del tanque 1 desplazan los residuos del gemelo igual que un ataque lento. Por eso hay unas 17 alarmas cortas por hora en operación normal, concentradas en esas perturbaciones.
- **Identificación.** Un sesgo sobre FT-101 que no alcance a alterar el residuo de LT-101 se confunde con un ataque al actuador P-101, porque ambas firmas contienen el caudal.
