# Desliga o MemeCoinAI iniciado a partir DESTA pasta e salva uma cópia do banco.
# Só considera processos Python cuja linha de comando aponta para o .venv deste projeto,
# para nunca encerrar outros programas Python da máquina.
$venv = Join-Path $PSScriptRoot 'backend\.venv'
$py = Join-Path $venv 'Scripts\python.exe'
function Find-Project($pattern) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$venv*" -and $_.CommandLine -match $pattern }
}
# O supervisor sai primeiro: senão ele reabriria os outros.
$found = $false
$killed = @()
foreach ($pattern in 'app\.supervisor', 'uvicorn app\.main|app\.worker|app\.live|app\.tape|app\.safety|app\.board') {
    foreach ($p in Find-Project $pattern) {
        $found = $true
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $killed += $p.ProcessId
        Write-Host "Encerrado: PID $($p.ProcessId)"
    }
}
# Os workers da API (uvicorn --workers) rodam pelo Python do sistema, fora do .venv: encerra os filhos dos que fechamos.
foreach ($c in Get-CimInstance Win32_Process -Filter "Name='python.exe'") {
    if ($c.CommandLine -match 'spawn_main\(parent_pid=(\d+)' -and ($killed -contains [int]$Matches[1] -or $killed -contains $c.ParentProcessId)) {
        Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Encerrado: PID $($c.ProcessId) (worker da API)"
    }
}
if (-not $found) { Write-Host 'Nenhum processo do MemeCoinAI em execução.' }
if (Test-Path $py) {
    Write-Host 'Salvando cópia do banco...'
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try { & $py -m app.cli backup } finally { Pop-Location }
}
