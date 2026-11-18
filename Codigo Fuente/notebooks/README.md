# Notebooks

Análisis exploratorio en Jupyter. Los notebooks **leen** datos de `data/` y resultados de `results/`, pero no contienen lógica que el sistema necesite: todo lo que se reutilice debe pasar a `src/fdisim`.

Notebooks previstos:

| Notebook | Fase | Propósito |
|---|---|---|
| `01_modelo_dos_tanques.ipynb` | 2 | Calibración de parámetros y sintonía del PID |
| `02_latencias_opcua.ipynb` | 3 | Latencias por salto, con y sin cifrado |
| `03_efecto_de_los_ataques.ipynb` | 4 | Efecto físico de sesgo, rampa y replay en lazo cerrado |
| `04_descubrimiento_causal.ipynb` | 5 | PCMCI vs. Granger vs. grafo físico (actividad 3.1) |
| `05_residuos_y_umbrales.ipynb` | 6 | Calibración de umbrales, CUSUM y EWMA |
| `06_resultados_oe4.ipynb` | 8 | Figuras del informe final y del artículo |

Convención: nombre `NN_tema.ipynb`; limpiar las salidas antes de hacer commit.
