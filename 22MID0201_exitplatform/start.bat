@echo off
title Exit Process Platform - Starting...
color 0A
cls

echo.
echo  ========================================
echo    Exit Process Platform
echo  ========================================
echo.
echo  Setting up... please wait.
echo.

:: Step 1 — Apply database migrations (safe to run every time, skips if already done)
echo  [1/3] Checking database...
cd /d %~dp0backend
.venv\Scripts\python.exe scripts/apply_migrations.py --seed >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Could not connect to the database.
    echo  Make sure you have internet access and try again.
    echo.
    pause
    exit /b 1
)
echo  [1/3] Database ready.

:: Step 2 — Start backend API server in a minimised window
echo  [2/3] Starting backend...
start /min "Exit Platform - Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
timeout /t 4 /nobreak >nul
echo  [2/3] Backend running.

:: Step 3 — Start frontend in a minimised window
echo  [3/3] Starting frontend...
start /min "Exit Platform - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 5 /nobreak >nul
echo  [3/3] Frontend running.

:: Open browser
echo.
echo  Opening browser...
start http://localhost:5173

cls
echo.
echo  ========================================
echo    Exit Process Platform is ready!
echo  ========================================
echo.
echo  Browser opened at: http://localhost:5173
echo.
echo  Login credentials:
echo.
echo    Employee : kirthana.mekala@example.com
echo    Manager  : arjun.menon@example.com
echo    HR       : priya.nair@example.com
echo.
echo    Password for all: ExitDemo!2026
echo.
echo  ========================================
echo.
echo  Keep this window open while using the app.
echo  Close it when you are done.
echo.
pause
