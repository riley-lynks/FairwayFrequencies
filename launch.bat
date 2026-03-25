@echo off
:: =============================================================================
:: launch.bat — Fairway Frequencies One-Click Launcher
:: =============================================================================
:: HOW TO USE:
::   Double-click this file. It will:
::   1. Start the Python web server in the background (no terminal window)
::   2. Wait 2 seconds for it to initialize
::   3. Open http://localhost:5000 in your default browser
::
:: TO STOP THE SERVER:
::   Open Task Manager > Details tab > find python.exe > End Task
::   OR just restart your computer (server doesn't persist across reboots)
:: =============================================================================

:: Change to the folder where this file lives (the project root)
cd /d "%~dp0"

:: Check if the server is already running by trying to reach it
:: WHY: If you double-click twice, we don't want two servers fighting over port 5000
curl -s http://localhost:5000/api/status >nul 2>&1
if %errorlevel% == 0 (
    echo Server is already running. Opening browser...
    start "" "http://localhost:5000"
    exit /b
)

:: Start the server using pythonw.exe — the "w" version runs with NO console window
:: WHY pythonw? Regular python.exe shows a black terminal window. pythonw.exe is silent.
:: The server runs invisibly in the background until you stop it or restart your PC.
start "" "C:\Users\riley\AppData\Local\Programs\Python\Python311\pythonw.exe" -X utf8 server.py

:: Wait 2 seconds for Flask to initialize before opening the browser
:: WHY: Flask takes ~1 second to start. If we open the browser too fast it gets a "refused" error.
timeout /t 2 /nobreak >nul

:: Open the control panel in your default browser
start "" "http://localhost:5000"
