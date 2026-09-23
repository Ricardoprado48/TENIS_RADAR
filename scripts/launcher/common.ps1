# Funcoes auxiliares do launcher local (LOTE I). Sem logica de dominio do
# radar/odds/screenshot_parser/forward test -- so orquestracao de processos.

function Test-TcpPort {
    param(
        [string]$ComputerName = '127.0.0.1',
        [Parameter(Mandatory = $true)][int]$Port
    )
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($ComputerName, $Port, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne(300)
        if ($connected -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

function Test-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 2
    )
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk -Url $Url -TimeoutSec 2) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-RuntimeDir {
    param([Parameter(Mandatory = $true)][string]$Root)
    $dir = Join-Path $Root '.runtime'
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    return $dir
}

# Remove um arquivo de PID orfao (processo daquele PID nao existe mais).
# Nunca mexe em processos -- so limpa o arquivo local quando ele ja nao
# corresponde a nada em execucao.
function Remove-StalePidFile {
    param(
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path $PidFile)) { return }
    $rawId = (Get-Content -Path $PidFile -Raw -ErrorAction SilentlyContinue)
    if ($rawId) { $rawId = $rawId.Trim() }
    $alive = $false
    if ($rawId) {
        $proc = Get-Process -Id $rawId -ErrorAction SilentlyContinue
        if ($proc) { $alive = $true }
    }
    if (-not $alive) {
        Write-Host "  ($Label`: arquivo PID antigo sem processo correspondente -- removendo)"
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
}
