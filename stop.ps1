# Encerra a API, o coletor e a atualização rápida do MemeCoinAI iniciados a partir DESTA pasta.
# Só considera processos Python cuja linha de comando aponta para o .venv deste projeto,
# para nunca encerrar outros programas Python da máquina.
$venv = Join-Path $PSScriptRoot 'backend\.venv'
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$venv*" -and $_.CommandLine -match 'uvicorn app\.main|app\.worker|app\.live|app.safety|app.board' }
if (-not $procs) { Write-Host 'Nenhum processo do MemeCoinAI em execução.'; exit 0 }
foreach ($p in $procs) {
    $kind = if ($p.CommandLine -match 'app\.worker') { 'coletor' } elseif ($p.CommandLine -match 'app\.live') { 'atualização rápida' } elseif ($p.CommandLine -match 'app.safety') { 'segurança' } elseif ($p.CommandLine -match 'app\.board') { 'painel' } else { 'API' }
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Encerrado: $kind (PID $($p.ProcessId))"
}
