@echo off
rem ============================================================
rem  cloudflare.example.bat
rem  Copy this file to cloudflare.bat and adjust the settings
rem  below to match your Cloudflare tunnel configuration.
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion

cd /d %~dp0

set "MCP_ROOT=%~dp0"

set "MCP_LAUNCHER_NAME=%~n0"

if "%MCP_ROOT:~-1%"=="\" set "MCP_ROOT=%MCP_ROOT:~0,-1%"

rem Uncomment and set these if you use a local proxy:
rem set "HTTP_PROXY=http://127.0.0.1:YOUR_PROXY_PORT"
rem set "HTTPS_PROXY=http://127.0.0.1:YOUR_PROXY_PORT"

set "CLOUDFLARE_EXE=%~dp0cloudflare.exe"
set "TUNNEL_NAME=your-tunnel-name"

set "MCP_LOG_DIR=%MCP_ROOT%\logs"
if "%MCP_LOG_KEEP_COUNT%"=="" set "MCP_LOG_KEEP_COUNT=10"
call :ensure_log_dir

call :build_run_stamp

set "CLOUDFLARE_LOG=%MCP_LOG_DIR%\%MCP_LAUNCHER_NAME%-%LOG_RUN_STAMP%.log"

type nul >> "%CLOUDFLARE_LOG%"

call :prune_logs "%MCP_LAUNCHER_NAME%-*.log"
set "CLOUDFLARE_LOG_LEVEL=debug"

set "CLOUDFLARE_TRANSPORT_LOG_LEVEL=debug"



call :log "Cloudflare tunnel launcher started"

call :log "Cloudflare log directory: %MCP_LOG_DIR%"
call :log "Cloudflare log: %CLOUDFLARE_LOG%"

call :log "Tunnel output will be mirrored to the console and %CLOUDFLARE_LOG%"

call :log "Cloudflare log retention count: %MCP_LOG_KEEP_COUNT%"
call :log "Cloudflare log level: %CLOUDFLARE_LOG_LEVEL%"

call :log "Cloudflare transport log level: %CLOUDFLARE_TRANSPORT_LOG_LEVEL%"

call :log "Cloudflare executable: %CLOUDFLARE_EXE%"

if not exist "%CLOUDFLARE_EXE%" (

  call :log "ERROR: Cloudflare executable not found: %CLOUDFLARE_EXE%"

  pause

  exit /b 1

)
>>"%CLOUDFLARE_LOG%" echo ============================================================

>>"%CLOUDFLARE_LOG%" echo [%DATE% %TIME%] Script start

>>"%CLOUDFLARE_LOG%" echo [%DATE% %TIME%] Found executable: %CLOUDFLARE_EXE%


:loop

call :log "Starting Cloudflare Tunnel with HTTP/2 and debug logging"

>>"%CLOUDFLARE_LOG%" echo [%DATE% %TIME%] Command: "%CLOUDFLARE_EXE%" tunnel --protocol http2 --loglevel %CLOUDFLARE_LOG_LEVEL% --transport-loglevel %CLOUDFLARE_TRANSPORT_LOG_LEVEL% run %TUNNEL_NAME%
powershell -NoProfile -ExecutionPolicy Bypass -Command ^

  "$ErrorActionPreference='Continue'; & '%CLOUDFLARE_EXE%' tunnel --protocol http2 --loglevel '%CLOUDFLARE_LOG_LEVEL%' --transport-loglevel '%CLOUDFLARE_TRANSPORT_LOG_LEVEL%' run '%TUNNEL_NAME%' 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } | Tee-Object -FilePath '%CLOUDFLARE_LOG%' -Append; $exitCode=$LASTEXITCODE; exit $exitCode"
set "CF_EXIT_CODE=%ERRORLEVEL%"

call :log "Tunnel stopped with exit code %CF_EXIT_CODE%"

call :emit_tail "%CLOUDFLARE_LOG%" 60

call :log "Restarting in 5 seconds"

timeout /t 5 >nul

goto loop



:ensure_log_dir

if not exist "%MCP_LOG_DIR%" mkdir "%MCP_LOG_DIR%" >nul 2>&1

exit /b 0



:build_run_stamp

set "LOG_RUN_STAMP="

for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-Date).ToString('yyyyMMdd-HHmmss-fff')"`) do set "LOG_RUN_STAMP=%%I"

if not defined LOG_RUN_STAMP set "LOG_RUN_STAMP=run-%RANDOM%-%RANDOM%"

exit /b 0



:prune_logs

set "LOG_PATTERN=%~1"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^

  "$logDir='%MCP_LOG_DIR%'; $pattern='%LOG_PATTERN%'; try { $keep=[int]'%MCP_LOG_KEEP_COUNT%' } catch { $keep=10 }; if ($keep -lt 1) { $keep=1 }; Get-ChildItem -Path $logDir -Filter $pattern -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending | Select-Object -Skip $keep | Remove-Item -Force -ErrorAction SilentlyContinue"

set "LOG_PATTERN="

exit /b 0


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
