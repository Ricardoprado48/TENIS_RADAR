# LOTE I -- Launcher local. So sobe/derruba processos (FastAPI + Vite dev
# server) e abre o navegador. Nao altera radar, odds, screenshot_parser,
# forward test ou calendario.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$Root = (Resolve-Path $Root).Path
$WebDir = Join-Path $Root 'web'
$RuntimeDir = Get-RuntimeDir -Root $Root

$BackendPidFile = Join-Path $RuntimeDir 'backend.pid'
$FrontendPidFile = Join-Path $RuntimeDir 'frontend.pid'
$BackendLog = Join-Path $RuntimeDir 'backend.log'
$BackendErrLog = Join-Path $RuntimeDir 'backend.err.log'
$FrontendLog = Join-Path $RuntimeDir 'frontend.log'
$FrontendErrLog = Join-Path $RuntimeDir 'frontend.err.log'

$BackendPort = 8000
$FrontendPort = 5173
$BackendHealthUrl = "http://127.0.0.1:$BackendPort/api/health"
$FrontendUrl = "http://127.0.0.1:$FrontendPort/"

Write-Host '=== Tennis Radar - iniciando ==='
Write-Host "Diretorio do projeto: $Root"

Remove-StalePidFile -PidFile $BackendPidFile -Label 'backend'
Remove-StalePidFile -PidFile $FrontendPidFile -Label 'frontend'

# --- 1) Python ---------------------------------------------------------
Write-Host "`n[1/4] Verificando Python..."
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host 'ERRO: "python" nao encontrado no PATH. Instale o Python 3 ou ajuste o PATH.' -ForegroundColor Red
    exit 1
}
& $python.Source -c 'import fastapi, uvicorn' *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERRO: dependencias Python ausentes (fastapi/uvicorn). Rode: pip install -r requirements.txt' -ForegroundColor Red
    exit 1
}
Write-Host "  OK ($($python.Source))"

# --- 2) Node/npm ---------------------------------------------------------
Write-Host "`n[2/4] Verificando Node/npm..."
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host 'ERRO: "node" nao encontrado no PATH. Instale o Node.js.' -ForegroundColor Red
    exit 1
}
$viteBin = Join-Path $WebDir 'node_modules\vite\bin\vite.js'
if (-not (Test-Path $viteBin)) {
    Write-Host 'ERRO: dependencias do frontend ausentes. Rode "npm install" dentro de web/.' -ForegroundColor Red
    exit 1
}
Write-Host "  OK ($($node.Source))"

# --- 3) Backend (FastAPI/uvicorn) ---------------------------------------
Write-Host "`n[3/4] Backend (FastAPI)..."
if (Test-TcpPort -Port $BackendPort) {
    if (Test-HttpOk -Url $BackendHealthUrl) {
        Write-Host "  Backend ja esta rodando em http://127.0.0.1:$BackendPort (reaproveitando)."
    } else {
        Write-Host "ERRO: porta $BackendPort ja esta em uso por outro processo (nao respondeu em $BackendHealthUrl). Abortando -- nada foi encerrado." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  Iniciando: python -m uvicorn api.main:app --host 127.0.0.1 --port $BackendPort"
    $backendProc = Start-Process -FilePath $python.Source `
        -ArgumentList @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError $BackendErrLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $BackendPidFile -Value $backendProc.Id -NoNewline
    Write-Host "  PID $($backendProc.Id) (log: $BackendLog)"

    Write-Host "  Aguardando $BackendHealthUrl responder (ate 60s)..."
    if (-not (Wait-ForHttp -Url $BackendHealthUrl -TimeoutSec 60)) {
        Write-Host "ERRO: backend nao respondeu em 60s. Veja $BackendLog e $BackendErrLog" -ForegroundColor Red
        exit 1
    }
}
Write-Host '  OK'

# --- 4) Frontend (Vite dev server) --------------------------------------
Write-Host "`n[4/4] Frontend (Vite dev server)..."
if (Test-TcpPort -Port $FrontendPort) {
    if (Test-HttpOk -Url $FrontendUrl) {
        Write-Host "  Frontend ja esta rodando em $FrontendUrl (reaproveitando)."
    } else {
        Write-Host "ERRO: porta $FrontendPort ja esta em uso por outro processo (nao respondeu em $FrontendUrl). Abortando -- nada foi encerrado." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  Iniciando: node node_modules/vite/bin/vite.js --host 127.0.0.1 --port $FrontendPort --strictPort (equivalente a 'npm run dev')"
    $frontendProc = Start-Process -FilePath $node.Source `
        -ArgumentList @($viteBin, '--host', '127.0.0.1', '--port', "$FrontendPort", '--strictPort') `
        -WorkingDirectory $WebDir `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError $FrontendErrLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $FrontendPidFile -Value $frontendProc.Id -NoNewline
    Write-Host "  PID $($frontendProc.Id) (log: $FrontendLog)"

    Write-Host "  Aguardando $FrontendUrl responder (ate 60s)..."
    if (-not (Wait-ForHttp -Url $FrontendUrl -TimeoutSec 60)) {
        Write-Host "ERRO: frontend nao respondeu em 60s. Veja $FrontendLog e $FrontendErrLog" -ForegroundColor Red
        exit 1
    }
}
Write-Host '  OK'

Start-Process $FrontendUrl

Write-Host "`nTennis Radar iniciado com sucesso."
Write-Host "  Frontend: $FrontendUrl"
Write-Host "  Backend:  $BackendHealthUrl"
Write-Host "  Logs:     $RuntimeDir"
Write-Host "`nPara encerrar, execute ENCERRAR_TENNIS_RADAR.bat"
exit 0

