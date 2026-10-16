@echo off
rem Start RPG Roleplay (Postgres, backend, frontend) and open it in the browser.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\local.ps1" start %*
if errorlevel 1 pause
