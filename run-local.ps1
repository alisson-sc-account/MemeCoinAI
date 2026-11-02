# Sobe o MemeCoinAI localmente: API + interface em http://127.0.0.1:8000, o coletor contínuo
# e a atualização rápida do quadro "Quando vender" (10 s).
# Uso: powershell -ExecutionPolicy Bypass -File .\run-local.ps1          (prepara e inicia)
#      powershell -ExecutionPolicy Bypass -File .\run-local.ps1 -NoStart (só prepara/verifica)
param([switch]$NoStart, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$py = Join-Path $backend '.venv\Scripts\python.exe'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# 1. Ambiente Python
if (-not (Test-Path $py)) {
    Step 'Criando ambiente Python (backend/.venv)'
    python -m venv (Join-Path $backend '.venv')
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -e "$backend[dev]" -q
}

# 2. Configuração local (.env nunca vai para o Git)
$envFile = Join-Path $backend '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $backend '.env.example') $envFile
    Write-Host "Criado backend/.env a partir do exemplo. Defina SEED_INITIAL_PASSWORD nele e rode de novo." -ForegroundColor Yellow
    exit 1
}

# 3. Banco e usuários (idempotente: não altera senhas existentes)
Push-Location $backend
try {
    Step 'Aplicando migrações'
    & $py -m app.cli migrate | Out-Null
    Step 'Garantindo usuários iniciais'
    & $py -m app.cli seed-users
} finally { Pop-Location }

# 4. Interface (build servido pela própria API)
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Step 'Instalando dependências do frontend (npm install)'
    Push-Location $frontend; try { npm install } finally { Pop-Location }
}
$dist = Join-Path $frontend 'dist\index.html'
$newestSrc = Get-ChildItem (Join-Path $frontend 'src') -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not (Test-Path $dist) -or $newestSrc.LastWriteTime -gt (Get-Item $dist).LastWriteTime) {
    Step 'Gerando build da interface (npm run build)'
    Push-Location $frontend; try { npm run build } finally { Pop-Location }
}

# 5. Porta livre?
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "A porta $Port já está em uso (PID $($busy[0].OwningProcess)). Feche a outra API ou use -Port 8010." -ForegroundColor Yellow
    if (-not $NoStart) { exit 1 }
}

if ($NoStart) { Step 'Preparação concluída (-NoStart: nada foi iniciado)'; exit 0 }

# 6. Tudo numa janela só: reinicia o que cair e salva o banco ao desligar (Ctrl+C ou stop.bat)
Step "Abra http://127.0.0.1:$Port no navegador"
Push-Location $backend
try { & $py -m app.supervisor --port $Port } finally { Pop-Location }
