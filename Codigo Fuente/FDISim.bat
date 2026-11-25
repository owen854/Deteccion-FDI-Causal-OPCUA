@echo off
rem FDISim-OPCUA: abre el aplicativo completo (HMI web) con un doble clic (RF-48, RNF-14).
rem La primera vez crea los certificados y, si no hay modelo causal, lo genera (unos minutos).
cd /d "%~dp0"
if not exist ".venv\Scripts\fdisim.exe" (
  echo No se encontro el entorno virtual. Ejecute primero instalar.bat
  pause
  exit /b 1
)
set PYTHONUTF8=1
".venv\Scripts\fdisim.exe" ui
if errorlevel 1 pause
