@echo off
setlocal

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "BACKEND_DIR=%ROOT%\backend"
set "FRONTEND_DIR=%ROOT%\frontend"

if not exist "%BACKEND_DIR%\app\main.py" (
  echo Backend directory not found: "%BACKEND_DIR%"
  exit /b 1
)

if not exist "%FRONTEND_DIR%\package.json" (
  echo Frontend directory not found: "%FRONTEND_DIR%"
  exit /b 1
)

echo Starting backend and frontend dev servers...
echo Backend:  http://127.0.0.1:8001/docs
echo Frontend: http://127.0.0.1:5173

start "Rock PVP Backend" /D "%BACKEND_DIR%" cmd.exe /k python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --access-log --log-level info
start "Rock PVP Frontend" /D "%FRONTEND_DIR%" cmd.exe /k npm.cmd run dev

endlocal
