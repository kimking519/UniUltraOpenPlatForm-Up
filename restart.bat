@echo off
echo Stopping Python processes...
taskkill /F /IM python.exe 2>nul
if %errorlevel% neq 0 (
    echo No Python processes found
) else (
    echo Python processes stopped
)

echo Starting application...
cd /d E:\WorkPlace\7_AI_APP\UniUltraOpenPlatForm
start "" python main.py

echo Application restarted