@echo off
setlocal
set "ROOT=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\launcher\stop_tennis_radar.ps1" -Root "%ROOT%"
set "RESULT=%ERRORLEVEL%"

pause
exit /b %RESULT%
