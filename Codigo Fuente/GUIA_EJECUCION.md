# Guía de ejecución de FDISim-OPCUA

Cómo pasar de un computador sin nada instalado al aplicativo funcionando, en tres pasos:

1. obtener el código;
2. instalar, una sola vez;
3. abrir el aplicativo con `fdisim ui`.

No hace falta correr los comandos de prueba de cada fase. Tampoco hace falta abrir **UaExpert** ni **Wireshark**: el aplicativo levanta solo todos sus componentes OPC UA (ver la [sección 5](#5-hay-que-abrir-uaexpert)).

Todos los comandos son para **PowerShell** en Windows 10 u 11.

---

## 0. Requisitos

| Requisito | Detalle |
|---|---|
| Python 3.12 | Descárguelo de [python.org](https://www.python.org/downloads/). En el instalador, marque «Add python.exe to PATH» y deje activado el *py launcher*. **No** use Python 3.14: algunas bibliotecas científicas aún no lo soportan. |
| Git | Para clonar el repositorio. También puede descargarlo como ZIP desde GitHub. |
| Internet | Solo durante la instalación de dependencias. |
| Puertos libres | 4840 (planta), 4841 (gateway) y 8080 (interfaz web). |

Compruebe que tiene Python 3.12:

```powershell
py -3.12 --version
```

## 1. Obtener el código

```powershell
git clone https://github.com/owen854/Deteccion-FDI-Causal-OPCUA.git
```

```powershell
cd "Deteccion-FDI-Causal-OPCUA\Codigo Fuente"
```

Mientras el PR de las Fases 6 y 7 no esté fusionado en `main`, cambie a su rama:

```powershell
git checkout feature/fases-6-7-deteccion-hmi
```

Si ya tenía el repositorio clonado, actualícelo con `git pull` en lugar de clonarlo otra vez.

> Todos los comandos siguientes se ejecutan dentro de la carpeta `Codigo Fuente`.

## 2. Instalar (una sola vez)

**Opción A, con doble clic:** abra `instalar.bat`. Crea el entorno virtual `.venv` e instala las versiones exactas de las dependencias. Tarda unos minutos.

**Opción B, con comandos** (hacen lo mismo que el `.bat`):

```powershell
py -3.12 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

```powershell
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

Comprobación opcional (todo debe salir en OK):

```powershell
.\.venv\Scripts\python.exe scripts\verificar_entorno.py
```

## 3. Abrir el aplicativo

**Opción A, con doble clic:** abra `FDISim.bat`.

**Opción B, con comandos:** primero active el entorno virtual.

```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea el script («la ejecución de scripts está deshabilitada»), habilítelo solo para esa ventana y vuelva a activar el entorno:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Luego abra el aplicativo:

```powershell
fdisim ui
```

`fdisim` sin argumentos hace lo mismo. Sin activar el entorno, el equivalente es `.\.venv\Scripts\fdisim.exe ui`.

Se abre el navegador en **http://127.0.0.1:8080**. La ventana de la terminal es el servidor del aplicativo: déjela abierta mientras lo usa y ciérrelo con **Ctrl+C**.

### La primera vez: preparación automática

Al abrir por primera vez, el aplicativo prepara todo lo que falta. El avance aparece en la página **Experimentos**, en la línea «Preparación del aplicativo».

| Paso | Qué crea | Tiempo aproximado |
|---|---|---|
| Certificados X.509 y contraseñas de prueba | `certs/` (no se versiona) | segundos |
| Dataset de entrenamiento, validación y prueba (32 corridas simuladas) | `data/processed/v1/` | unos 3 min |
| Modelo causal y calibración de los detectores | `data/models/causal_v1/` | 1 a 2 min |

En total, unos 5 minutos. Espere a que diga **«listo»** antes de pulsar *Iniciar*. Las siguientes veces el aplicativo abre en segundos, porque todo eso ya existe.

Si prefiere hacer la preparación a mano y ver el avance en la consola, estos tres comandos equivalen a la preparación automática:

```powershell
fdisim certs
```

```powershell
fdisim dataset
```

```powershell
fdisim train --data data/processed/v1/train.parquet
```

## 4. Primera corrida (demostración de unos 5 minutos)

1. **Experimentos.** Elija el escenario `normal`, el modo **En red (OPC UA)**, una duración de `600` s y una escala de `5`. Pulse **Iniciar**. La planta, el gateway, el controlador y el monitor arrancan solos; en la bitácora de la página se ve el avance.
2. Espere a que el tiempo simulado del encabezado pase de **60 s**: es el arranque del detector, durante el cual no emite alarmas.
3. En **Armar un ataque**, deje Sesgo, LT-102, b = 2 y el sigilo activado, y pulse **Armar ahora**.
4. **Detección.** El residuo del gemelo de LT-102 cruza su umbral y el encabezado se pone rojo con «ALARMA causal · sospechosa LT-102». El método base sigue en «Normal».
5. **Grafo causal.** El nodo LT-102 aparece en rojo.
6. **Operación.** El nivel recibido sube 2 cm, con el ataque sombreado: es lo que ve el operador, mientras el lazo baja el nivel real.
7. Al terminar la corrida, **Resultados** la muestra con el ataque detectado y la variable identificada.

Una corrida en red dura su duración dividida por la escala: 600 s a 5× son unos 2 minutos. Para algo inmediato elija el modo **Offline**: un escenario de 30 min se simula en segundos y su detección aparece en Detección y en Resultados.

## 5. ¿Hay que abrir UaExpert?

**No.** Todo se lanza por comando o desde la interfaz:

- Al pulsar **Iniciar** (o con `fdisim run`), el aplicativo levanta como procesos propios el servidor OPC UA de la planta, el gateway, el controlador PI y el monitor con los detectores, todos con comunicación cifrada (SignAndEncrypt).
- La propia interfaz web es el cliente OPC UA del operador: muestra lo que publica el gateway.

UaExpert y Wireshark solo sirven para **verificar por fuera**, como se hizo en la Fase 1, que el sistema es interoperable con un cliente comercial y que el tráfico viaja cifrado. Es opcional. Si quiere mostrarlo:

1. Abra UaExpert una vez para que genere su certificado y ciérrelo.
2. Autorice ese certificado en la planta y el gateway del simulador:

   ```powershell
   fdisim certs --confiar-uaexpert
   ```

3. Con una corrida **en red** en curso, en UaExpert use *Server → Add*:
   - URL: `opc.tcp://127.0.0.1:4841/fdisim/gateway`;
   - política **Basic256Sha256** y modo **Sign & Encrypt**;
   - usuario `uaexpert` y la contraseña que está en `certs\credenciales.json`.
4. Acepte el certificado del gateway y arrastre `Tanque1/Nivel`, `Tanque2/Nivel`, `Bomba/Comando` y `Control/Consigna` a la vista de datos. Si arma un ataque desde la interfaz, UaExpert también verá el valor falso: para él, como para cualquier cliente, el dato es válido.

## 6. Uso diario (después de la primera vez)

Doble clic en `FDISim.bat`, o bien:

```powershell
cd "Deteccion-FDI-Causal-OPCUA\Codigo Fuente"
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
fdisim
```

## 7. Alternativa sin interfaz (consola)

El mismo trabajo se puede hacer solo con comandos. Al terminar, cada corrida imprime sus criterios y el resultado de la detección.

| Comando | Qué hace |
|---|---|
| `fdisim run --scenario config/scenarios/sesgo_lt102.yaml --escala 5` | Corrida en red con un sesgo sobre LT-102 |
| `fdisim run --mode offline --scenario config/scenarios/rampa_lt101.yaml` | Corrida offline, en segundos |
| `fdisim run --scenario config/scenarios/normal.yaml --duracion 600 --escala 5 --ui` | Corrida en red con la interfaz abierta solo para observarla |
| `fdisim detect --data data/processed/v1/test.parquet` | Evalúa el detector causal frente al método base y deja el reporte en `results/deteccion_v1/` |

## 8. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `py` no se reconoce, o no existe Python 3.12 | Instale Python 3.12 desde python.org con el *py launcher*. |
| `fdisim` no se reconoce | Active el entorno (`.\.venv\Scripts\Activate.ps1`) o use `.\.venv\Scripts\fdisim.exe`. |
| «La ejecución de scripts está deshabilitada» al activar | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` en esa ventana. |
| «El puerto 4840 ya está en uso» | Hay otra corrida, o el servidor de la prueba de concepto de la Fase 1, abierto. Ciérrelo (Ctrl+C en su terminal). |
| El navegador no se abre | Entre a mano a http://127.0.0.1:8080. Si el puerto 8080 está ocupado: `fdisim ui --port 8090`. |
| El botón **Iniciar** está deshabilitado | Hay una corrida en curso, o la preparación aún no dice «listo». |
| El encabezado dice «Sin conexión» | No hay una corrida en red en curso: inicie una desde Experimentos. |
| El encabezado dice «Detección inactiva» | La corrida no es en red, o aún no pasan los 60 s de arranque del detector. |
| Windows pide permiso de red para Python | Puede aceptarlo para redes privadas. Todo funciona en `127.0.0.1` y no sale del equipo. |

Más detalle en el [manual de usuario](docs/manual_usuario.md) y en la [guía del detector](docs/guia_deteccion.md).
