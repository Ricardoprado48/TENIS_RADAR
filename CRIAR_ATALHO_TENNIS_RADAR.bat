@echo off
setlocal
set "ROOT=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$link = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Tennis Radar.lnk'));" ^
    "$link.TargetPath = '%ROOT%INICIAR_TENNIS_RADAR.bat';" ^
    "$link.WorkingDirectory = '%ROOT%';" ^
    "$link.IconLocation = '%SystemRoot%\System32\SHELL32.dll,13';" ^
    "$link.Save()"

echo Atalho "Tennis Radar" criado na Area de Trabalho.
pause
