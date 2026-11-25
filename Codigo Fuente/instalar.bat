@echo off
rem FDISim-OPCUA: instalacion en un entorno virtual con un solo comando (RNF-19).
rem Requiere Python 3.12 (https://www.python.org/downloads/). Despues abra FDISim.bat.
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 (
  echo No se pudo crear el entorno: instale Python 3.12 y repita.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 (
  echo Fallo la instalacion de dependencias.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -e . --no-deps
echo.
echo Instalacion terminada. Abra el aplicativo con FDISim.bat
pause
