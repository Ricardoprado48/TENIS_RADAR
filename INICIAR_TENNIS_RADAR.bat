@echo off
setlocal

set "ROOT=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\launcher\start_tennis_radar.ps1" -Root "%ROOT%"

if errorlevel 1 (
    echo.
    echo Falha ao iniciar o Tennis Radar. Veja as mensagens acima.
    echo Pressione qualquer tecla para continuar...
    pause >nul
)

endlocal
