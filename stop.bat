@echo off
rem Encerra a API e o coletor do MemeCoinAI desta pasta (nao afeta outros programas Python).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
