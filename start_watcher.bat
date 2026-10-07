@echo off
setlocal
cd /d "%~dp0"
title Startplatzboerse Watcher - dieses Fenster offen lassen!

echo ============================================================
echo   Startplatzboerse Watcher
echo   Dieses Fenster offen lassen, solange gesucht werden soll.
echo   Zum Beenden: Fenster schliessen.
echo ============================================================
echo.

rem --- 1. Install uv if it is missing ---------------------------------
where uv >nul 2>nul
if %errorlevel%==0 goto :have_uv

if exist "%USERPROFILE%\.local\bin\uv.exe" goto :add_path

echo [1/3] Installiere uv (einmalig) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if not exist "%USERPROFILE%\.local\bin\uv.exe" (
    echo.
    echo FEHLER: uv konnte nicht installiert werden. Internetverbindung pruefen.
    pause
    exit /b 1
)

:add_path
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

:have_uv
echo [2/3] Bereite Python und Browser vor (beim ersten Mal ein paar Minuten) ...
echo [3/3] Starte Watcher ...
echo.

rem --- 2. Run the script; uv installs Python + Playwright by itself ----
uv run boerse_watch.py

echo.
echo Der Watcher wurde beendet. Bei Problemen diesen Text an Simeon schicken.
pause
