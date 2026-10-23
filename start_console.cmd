@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Crie o ambiente e instale as dependencias conforme docs\RESEARCH_CONSOLE.md.
  exit /b 1
)
".venv\Scripts\python.exe" -m research_console %*
