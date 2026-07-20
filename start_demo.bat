@echo off
:: Check for Administrator privileges
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :run
) else (
    echo Requesting Administrator privileges to interact with Lenovo Legion Toolkit...
    powershell -Command "Start-Process '%~dpnx0' -Verb RunAs"
    exit /b
)

:run
cd /d "%~dp0"
echo ======================================================
echo THERVO - DEMONSTRATION LAUNCHER (ADMINISTRATOR)
echo ======================================================
echo Starting THERVO demonstration...
python scripts\run_demo.py
pause
