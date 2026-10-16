@echo off
rem Stop RPG Roleplay (frontend, backend, Postgres).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\local.ps1" stop %*
if errorlevel 1 pause
