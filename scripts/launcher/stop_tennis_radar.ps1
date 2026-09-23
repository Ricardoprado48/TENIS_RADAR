# LOTE I -- Encerra SOMENTE os processos iniciados por
# start_tennis_radar.ps1 (via arquivos .runtime/*.pid). Nunca usa
# taskkill /IM (mataria processos python/node de outros projetos).

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$Root = (Resolve-Path $Root).Path
$RuntimeDir = Join-Path $Root '.runtime'

function Stop-TrackedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path $PidFile)) {
        Write-Host "$Label`: nenhum PID registrado (nao foi iniciado por este launcher, ou ja foi encerrado)."
        return
    }

    $rawId = (Get-Content -Path $PidFile -Raw -ErrorAction SilentlyContinue)
    if ($rawId) { $rawId = $rawId.Trim() }

    if (-not $rawId) {
        Write-Host "$Label`: arquivo de PID vazio/invalido -- removendo."
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        return
    }

    $proc = Get-Process -Id $rawId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "$Label`: processo PID $rawId ja nao existe -- limpando arquivo."
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        return
    }

    Write-Host "$Label`: encerrando PID $rawId (e eventuais processos filhos)..."
    & taskkill /PID $rawId /T /F *> $null
    Start-Sleep -Milliseconds 300

    $stillThere = Get-Process -Id $rawId -ErrorAction SilentlyContinue
    if ($stillThere) {
        Write-Host "$Label`: AVISO -- processo PID $rawId ainda aparece ativo apos taskkill." -ForegroundColor Yellow
    } else {
        Write-Host "$Label`: encerrado."
    }
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
}

Write-Host '=== Tennis Radar - encerrando ==='

Stop-TrackedProcess -PidFile (Join-Path $RuntimeDir 'frontend.pid') -Label 'Frontend'
Stop-TrackedProcess -PidFile (Join-Path $RuntimeDir 'backend.pid') -Label 'Backend'

Write-Host "`nEncerramento concluido. Logs preservados em: $RuntimeDir"
exit 0
