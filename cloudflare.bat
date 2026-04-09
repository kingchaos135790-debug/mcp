@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d %~dp0

set "HTTP_PROXY=http://127.0.0.1:7890"
set "HTTPS_PROXY=http://127.0.0.1:7890"
set "TUNNEL_NAME=godotmcp"
set "MCP_LOG_DIR=%~dp0"
if "%MCP_LOG_DIR:~-1%"=="\" set "MCP_LOG_DIR=%MCP_LOG_DIR:~0,-1%"
set "CLOUDFLARE_LOG=%MCP_LOG_DIR%\cloudflare-tunnel.log"

call :log "Cloudflare tunnel launcher started"
call :log "Cloudflare log: %CLOUDFLARE_LOG%"
>>"%CLOUDFLARE_LOG%" echo ============================================================
>>"%CLOUDFLARE_LOG%" echo [%DATE% %TIME%] Script start
where cloudflare.exe >>"%CLOUDFLARE_LOG%" 2>&1

:loop
call :log "Starting Cloudflare Tunnel with HTTP/2"
>>"%CLOUDFLARE_LOG%" echo [%DATE% %TIME%] Command: cloudflare.exe tunnel --protocol http2 run %TUNNEL_NAME%
cloudflare.exe tunnel --protocol http2 run %TUNNEL_NAME% 1>>"%CLOUDFLARE_LOG%" 2>&1
set "CF_EXIT_CODE=%ERRORLEVEL%"
call :log "Tunnel stopped with exit code %CF_EXIT_CODE%"
call :emit_tail "%CLOUDFLARE_LOG%" 60
call :log "Restarting in 5 seconds"
timeout /t 5 >nul
goto loop

:emit_tail
set "TAIL_PATH=%~1"
set "TAIL_COUNT=%~2"
if not exist "%TAIL_PATH%" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$path='%TAIL_PATH%'; $count=[int]'%TAIL_COUNT%'; Write-Host ('----- BEGIN TAIL: ' + $path + ' -----'); Get-Content -Path $path -Tail $count; Write-Host ('----- END TAIL: ' + $path + ' -----')"
exit /b 0

:log
if not exist "%MCP_LOG_DIR%" mkdir "%MCP_LOG_DIR%" >nul 2>&1
set "LOG_LINE=[%DATE% %TIME%] %~1"
echo %LOG_LINE%
>>"%CLOUDFLARE_LOG%" echo %LOG_LINE%
set "LOG_LINE="
exit /b 0
