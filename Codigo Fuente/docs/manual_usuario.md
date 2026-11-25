# Manual de usuario de FDISim-OPCUA (versión 1)

FDISim-OPCUA simula una planta de dos tanques controlada a través de OPC UA cifrado, inyecta ataques de datos falsos desde un gateway comprometido y los detecta con un modelo causal. Todo se maneja desde una interfaz web en español.

## 1. Instalación (una sola vez)

1. Instale **Python 3.12** desde python.org (marque «Add python.exe to PATH»).
2. Dé doble clic en **`instalar.bat`**, en la carpeta `Codigo Fuente`. El script crea el entorno virtual e instala las versiones fijadas de las dependencias (RNF-19).

Equivalente en consola:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps
```

## 2. Abrir el aplicativo: un solo paso

Dé doble clic en **`FDISim.bat`**. También puede abrirlo en consola con `fdisim` (sin argumentos) o con `fdisim ui`. El navegador se abre en `http://127.0.0.1:8080`.

La **primera vez**, el aplicativo se prepara solo y muestra el avance en la página **Experimentos**:

- crea los certificados X.509 que falten;
- si no hay modelo causal, genera el dataset y entrena y calibra el modelo (unos minutos).

Cuando aparece «Preparación del aplicativo: listo», ya puede iniciar corridas.

## 3. Páginas

| Página | Para qué sirve |
|---|---|
| **Operación** | Sinóptico de los tanques, tendencias de niveles (con el ataque sombreado), bomba y caudal; cambio de consigna. |
| **Experimentos** | Elegir el escenario, el modo (en red u offline), la duración, la escala y la semilla, e **Iniciar** o **Detener** la corrida. Armar ataques en caliente y ver la bitácora. |
| **Detección** | Residuos del gemelo causal y a un paso divididos por su límite (umbral = ±1), acumuladores CUSUM, alarmas causal frente a base y tabla de alarmas con el botón **Reconocer**. Sin corrida en curso, muestra la última corrida guardada o la que elija. |
| **Grafo causal** | Grafo de referencia: en rojo la variable sospechosa y en ámbar los residuos en alarma. Comparación del grafo físico con los aprendidos. |
| **Resultados** | Evaluación de ambos detectores sobre el dataset de prueba, resultado por corrida y descarga de CSV y reporte. |
| **Comunicaciones** | Endpoints, seguridad configurada, sesión de la HMI y latencias medidas. |

El **encabezado** de todas las páginas muestra el estado de la conexión, el tiempo simulado, la seguridad y el indicador de alarma:

- **rojo:** alarma del detector causal, con la variable sospechosa;
- **ámbar:** alarma solo del método base;
- **verde:** sin alarmas.

## 4. Demostración sugerida (unos 5 minutos)

1. **Experimentos.** Elija el escenario `normal`, el modo **En red**, una duración de 600 s y una escala de 5. Pulse **Iniciar**.
2. Espere a que el tiempo simulado pase de 60 s; antes de eso el detector no emite alarmas. En **Armar un ataque**, deje Sesgo, LT-102, b = 2 y sigilo activado, y pulse **Armar ahora**.
3. **Detección.** El residuo del gemelo de LT-102 cruza el umbral, el encabezado se pone rojo con «sospechosa LT-102» y el método base sigue normal.
4. **Grafo causal.** El nodo LT-102 aparece en rojo.
5. **Operación.** El nivel recibido sube 2 cm y el ataque se ve sombreado. Es lo que «ve» el operador, mientras el lazo baja el nivel real.
6. Al terminar, **Resultados** muestra la corrida con el ataque detectado y la variable identificada.

Para una corrida rápida sin red, elija el modo **Offline**: un escenario de 30 min se simula en segundos y su detección aparece en Detección y Resultados.

## 5. Comandos de consola (opcional)

| Comando | Qué hace |
|---|---|
| `fdisim run --scenario config/scenarios/sesgo_lt102.yaml --escala 5` | Corrida en red; al final reprocesa con los detectores |
| `fdisim run --mode offline --scenario config/scenarios/rampa_lt101.yaml` | Corrida offline con detección |
| `fdisim detect --data data/processed/v1/test.parquet` | Evalúa ambos detectores sobre el dataset de prueba |
| `fdisim detect --run data/raw/<run_id>` | Reprocesa una corrida guardada |
| `fdisim dataset` · `fdisim train --data data/processed/v1/train.parquet` | Regeneran el dataset y el modelo |

## 6. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| «El puerto 4840 ya está en uso» | Hay otra corrida o el servidor de la prueba de concepto abierto: ciérrelo. |
| «Detección inactiva» en el encabezado | No hay una corrida en red en curso, o aún no se cumplen los 60 s de arranque. |
| La HMI muestra «Sin conexión» | No hay una corrida en red en curso: inicie una desde Experimentos. |
| El botón Iniciar está deshabilitado | Hay una corrida en curso o el aplicativo aún se está preparando. |
