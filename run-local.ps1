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

# 6. Coletor contínuo numa janela própria (feche a janela para parar)
Step 'Iniciando o coletor (nova janela)'
Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$py' -m app.worker"

# 7. Atualização rápida (preço a cada 10 s no quadro "Quando vender") numa janela própria
Step 'Iniciando a atualização rápida (nova janela)'
Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$py' -m app.live"

# Segurança das moedas (rug pull, carteiras novas, mapa de carteiras) numa janela própria
Step 'Iniciando a verificação de segurança (nova janela)'
Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$py' -m app.safety"

# Listas do site prontas em segundo plano
Step 'Iniciando o painel (nova janela)'
Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$py' -m app.board"

# 8. API + interface nesta janela (Ctrl+C para parar)
Step "Abra http://127.0.0.1:$Port no navegador"
Push-Location $backend
try { & $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port } finally { Pop-Location }
