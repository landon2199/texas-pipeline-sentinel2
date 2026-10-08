@echo off
rem GEOG 392 Group 10: the GeoAI dashboard (map + "ask the map" panel) at http://127.0.0.1:8392
rem Double-click to start it. Your browser opens the page after about 15 seconds.
rem It is a small local web server: it only works while this window is open, and it uses no CPU while idle.
rem Close this window (or press Ctrl+C) to stop it.
title GEOG 392 GeoAI dashboard - close this window to stop it
rem Ollama runs at the desktop's Tailscale address, kept outside the repository in %USERPROFILE%\.geog392\ollama_host.txt
if not defined OLLAMA_HOST if exist "%USERPROFILE%\.geog392\ollama_host.txt" set /p OLLAMA_HOST=<"%USERPROFILE%\.geog392\ollama_host.txt"
cd /d "%~dp0"
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 15; Start-Process 'http://127.0.0.1:8392'"
"C:\Users\Landon\.geog392\venv\Scripts\python.exe" ai_dashboard.py
pause
