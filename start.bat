@echo off
rem Inicia o MemeCoinAI localmente: API + interface em http://127.0.0.1:8000, o coletor
rem e a atualizacao rapida do quadro "Quando vender".
rem Equivale a: powershell -ExecutionPolicy Bypass -File run-local.ps1
rem A politica de execucao e ignorada so para este script; nada e alterado no sistema.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-local.ps1" %*
