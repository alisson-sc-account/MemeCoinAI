# Início rápido no Windows

Requisitos: Windows 10/11, Python 3.11 ou mais novo (testado com 3.14.7), Node 20 ou mais novo (testado com 24), internet. Não precisa de Docker, Linux, nuvem nem chave de API.

## 1. Primeira vez

1. Abra a pasta do projeto no Explorador.
2. Dê dois cliques em **`start.bat`** (ou rode no terminal: `.\start.bat`).
3. Na primeira execução ele cria `backend\.env` a partir do exemplo e para. Abra `backend\.env`, defina `SEED_INITIAL_PASSWORD` e rode `start.bat` de novo.
4. O script cria o ambiente Python, aplica as migrações do banco, cria os usuários, instala e gera a interface quando necessário, abre o **coletor** numa janela própria e sobe a **API + interface**.
5. Abra **http://127.0.0.1:8000** e entre com `natan` ou `alisson` e a senha definida.

## 2. Uso diário

- **Iniciar:** `start.bat`. O coletor abre em outra janela; a API fica na janela do script.
- **Parar:** `stop.bat` (encerra só a API e o coletor desta pasta) ou feche as duas janelas.
- O monitoramento só acontece com o computador ligado e o coletor rodando. Com ele parado, o Dashboard mostra **Coletor parado** e os dados aparecem como atrasados.

## 3. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "A porta 8000 já está em uso" | Outra API do projeto ainda aberta | `stop.bat`, depois `start.bat`; ou `start.bat -Port 8010` |
| Janela do coletor fecha com "outro worker já está rodando" | Já existe um coletor (trava em `backend\data\worker.lock`) | Normal: só um coletor por banco. Use `stop.bat` para reiniciar |
| Dashboard mostra **Coletor parado** | Janela do coletor fechada ou erro | Rode `start.bat` de novo e veja a janela do coletor |
| "Banco ocupado pelo coletor; tente de novo" | Escrita longa no SQLite (erro 503, temporário) | Atualiza sozinho em 30 s. Se persistir, `stop.bat` e `start.bat` |
| Concentração de holders "indisponível" | RPC público responde 429 | Limite da fonte gratuita; o ranking continua com cobertura menor |
| Poucos sinais de compra | O mercado no momento não passa nos critérios | Veja "Observar" em Compre agora; os critérios estão em `ANALYSIS_ENGINE.md` |
| `npm` ou `python` não encontrado | Não instalado ou fora do PATH | Instale Python e Node e abra um terminal novo |
| Execução de scripts bloqueada | Política do PowerShell | `start.bat` já ignora a política só para este script, sem alterar o sistema |

## 4. Backup do banco

O banco fica em `backend\data\memecoinai.db`. Para copiar com segurança: rode `stop.bat`, copie `memecoinai.db` (e os arquivos `-wal`/`-shm`, se existirem) e depois `start.bat`. Nunca apague o banco para "corrigir" um erro.

## 5. Testes

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest
cd ..\frontend; npm test; npm run typecheck; npm run lint; npm run build
```
