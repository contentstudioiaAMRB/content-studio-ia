@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Content Studio IA todavia no esta instalado. Haz doble clic en "1 - Instalar (Windows)".
  pause
  exit /b 1
)
".venv\Scripts\python.exe" content_studio.py
pause
