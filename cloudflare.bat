@echo off
cd /d %~dp0

:: ===== Proxy (optional, keep if you need it) =====
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890

:: ===== Tunnel name =====
set TUNNEL_NAME=godotmcp

:loop
echo [%date% %time%] Starting Cloudflare Tunnel...

cloudflare.exe tunnel run %TUNNEL_NAME%

echo [%date% %time%] Tunnel stopped! Restarting in 5 seconds...
timeout /t 5 >nul
goto loop