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
foreach ($pattern in 'app\.supervisor', 'uvicorn app\.main|app\.worker|app\.live|app\.tape|app\.safety|app\.board') {
    foreach ($p in Find-Project $pattern) {
        $found = $true
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Encerrado: PID $($p.ProcessId)"
    }
}
if (-not $found) { Write-Host 'Nenhum processo do MemeCoinAI em execução.' }
if (Test-Path $py) {
    Write-Host 'Salvando cópia do banco...'
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try { & $py -m app.cli backup } finally { Pop-Location }
}
