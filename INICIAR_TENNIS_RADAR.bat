@echo off
setlocal
set "ROOT=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\launcher\start_tennis_radar.ps1" -Root "%ROOT%"
set "RESULT=%ERRORLEVEL%"

echo.
if not "%RESULT%"=="0" (
    echo Falha ao iniciar o Tennis Radar. Veja as mensagens acima.
)
pause
exit /b %RESULT%
