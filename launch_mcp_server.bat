@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "MCP_ROOT=%~dp0"

set "MCP_LAUNCHER_NAME=%~n0"

if "%MCP_ROOT:~-1%"=="\" set "MCP_ROOT=%MCP_ROOT:~0,-1%"

set "MCP_DIR=E:\Program Files\mcp\windows-code-search-mcp"
set "WINDOWS_MCP_DIR=E:\Program Files\mcp\Windows-MCP"
set "SEARCH_ENGINE_DIR=E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
set "QDRANT_ROOT=E:\Program Files\qdrant"
set "QDRANT_EXE=%QDRANT_ROOT%\qdrant.exe"
set "QDRANT_START_BAT=%QDRANT_ROOT%\start-qdrant.bat"
set "QDRANT_CONFIG_PATH=%QDRANT_ROOT%\config\local.yaml"
set "QDRANT_URL=http://127.0.0.1:16333"
set "QDRANT_COLLECTION=code_chunks"
set "INDEX_ROOT=E:\mcp-index-data"
set "AUTO_INDEX_CONFIG_PATH=%MCP_DIR%\managed-repositories.json"
set "PYTHON_EXE=%WINDOWS_MCP_DIR%\.venv\Scripts\python.exe"
set "MCP_HOST=127.0.0.1"
set "MCP_PORT=8000"
set "VSCODE_BRIDGE_PORT=18876"
set "MCP_LOG_DIR=%MCP_ROOT%\logs"
if "%MCP_LOG_KEEP_COUNT%"=="" set "MCP_LOG_KEEP_COUNT=3"
call :ensure_log_dir

call :build_run_stamp

set "MCP_BOOT_LOG=%MCP_LOG_DIR%\%MCP_LAUNCHER_NAME%-launcher-%LOG_RUN_STAMP%.log"
set "MCP_STDIO_LOG=%MCP_LOG_DIR%\%MCP_LAUNCHER_NAME%-stdio-%LOG_RUN_STAMP%.log"
set "MCP_RUNTIME_LOG=%MCP_LOG_DIR%\%MCP_LAUNCHER_NAME%-runtime-%LOG_RUN_STAMP%.log"

type nul >> "%MCP_BOOT_LOG%"

type nul >> "%MCP_STDIO_LOG%"

type nul >> "%MCP_RUNTIME_LOG%"

call :prune_logs "%MCP_LAUNCHER_NAME%-launcher-*.log"

call :prune_logs "%MCP_LAUNCHER_NAME%-stdio-*.log"

call :prune_logs "%MCP_LAUNCHER_NAME%-runtime-*.log"

if "%FASTMCP_LOG_LEVEL%"=="" set "FASTMCP_LOG_LEVEL=DEBUG"
if "%FASTMCP_ENABLE_RICH_LOGGING%"=="" set "FASTMCP_ENABLE_RICH_LOGGING=false"
if "%FASTMCP_ENABLE_RICH_TRACEBACKS%"=="" set "FASTMCP_ENABLE_RICH_TRACEBACKS=false"
set "PYTHONUNBUFFERED=1"
set "PYTHONFAULTHANDLER=1"

call :log "Starting Windows code search MCP for ChatGPT developer mode"

call :log "Log directory: %MCP_LOG_DIR%"

call :log "Log retention count: %MCP_LOG_KEEP_COUNT%"
call :log "ripgrep is preferred for lexical search on this machine; local lexical fallback remains available when ripgrep is unavailable"
call :log "Transport: streamable-http"
call :log "HTTP session mode: stateless"
call :log "MCP host/port: %MCP_HOST%:%MCP_PORT%"
call :log "VS Code bridge port: %VSCODE_BRIDGE_PORT%"
call :log "FastMCP log level: %FASTMCP_LOG_LEVEL%"
call :log "Launcher log: %MCP_BOOT_LOG%"
call :log "Python stdio log: %MCP_STDIO_LOG%"
call :log "Python runtime log: %MCP_RUNTIME_LOG%"
call :log "Python process output will be mirrored to the console and %MCP_STDIO_LOG%"

if not exist "%MCP_DIR%" (
  call :log "ERROR: Integrated MCP folder not found: %MCP_DIR%"
  pause
  exit /b 1
)

if not exist "%WINDOWS_MCP_DIR%" (
  call :log "ERROR: Windows-MCP folder not found: %WINDOWS_MCP_DIR%"
  pause
  exit /b 1
)

if not exist "%SEARCH_ENGINE_DIR%\package.json" (
  call :log "ERROR: search engine package.json not found: %SEARCH_ENGINE_DIR%\package.json"
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  call :log "ERROR: python.exe not found in Windows-MCP venv: %PYTHON_EXE%"
  pause
  exit /b 1
)

if not exist "%QDRANT_EXE%" (
  call :log "ERROR: Qdrant executable not found: %QDRANT_EXE%"
  pause
  exit /b 1
)

if not exist "%QDRANT_CONFIG_PATH%" (
  call :log "ERROR: Qdrant config not found: %QDRANT_CONFIG_PATH%"
  pause
  exit /b 1
)

if not exist "%QDRANT_START_BAT%" (
  call :log "ERROR: Qdrant launcher not found: %QDRANT_START_BAT%"
  pause
  exit /b 1
)

rem ===== OAuth server-side config =====
set "OAUTH_ENABLED=true"
set "OAUTH_BASE_URL=https://mcp.laughman233.shop"
set "OAUTH_REDIRECT_URIS=https://chatgpt.com/connector/oauth/IPM1eV066eQL"
set "OAUTH_CLIENT_ID=windows"
set "OAUTH_CLIENT_SECRET=ls200126"
set "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD=client_secret_post"
set "OAUTH_REQUIRED_SCOPES=mcp:access"
set "OAUTH_VALID_SCOPES=mcp:access,offline_access"
set "OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION=false"
if "%OAUTH_STATE_MAX_TOKENS%"=="" set "OAUTH_STATE_MAX_TOKENS=10"

set "WINDOWS_MCP_DIR=%WINDOWS_MCP_DIR%"
set "SEARCH_ENGINE_DIR=%SEARCH_ENGINE_DIR%"
set "QDRANT_URL=%QDRANT_URL%"
set "QDRANT_COLLECTION=%QDRANT_COLLECTION%"
set "INDEX_ROOT=%INDEX_ROOT%"
set "AUTO_INDEX_CONFIG_PATH=%AUTO_INDEX_CONFIG_PATH%"
set "VSCODE_BRIDGE_PORT=%VSCODE_BRIDGE_PORT%"
set "FASTMCP_STATELESS_HTTP=true"
set "PYTHONPATH=%WINDOWS_MCP_DIR%\src;%MCP_DIR%"

call :log "OAuth base URL: %OAUTH_BASE_URL%"
call :log "Auto-index config: %AUTO_INDEX_CONFIG_PATH%"
call :log "Search engine dir: %SEARCH_ENGINE_DIR%"
call :log "Windows-MCP dir: %WINDOWS_MCP_DIR%"
call :log "Qdrant URL: %QDRANT_URL%"

call :detect_listener_pid
if defined MCP_LISTENER_PID (
  call :log "Port %MCP_HOST%:%MCP_PORT% is already in use by PID %MCP_LISTENER_PID%. Exiting without starting another copy."
  exit /b 0
)

call :log "Checking Qdrant at %QDRANT_URL%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$url='%QDRANT_URL%/collections'; $ok=$false; try { Invoke-WebRequest -UseBasicParsing $url | Out-Null; $ok=$true } catch {}; if (-not $ok) { Write-Host '[INFO] Qdrant is not reachable yet. Starting it now...'; Start-Process -FilePath '%QDRANT_START_BAT%' -WorkingDirectory '%QDRANT_ROOT%' -WindowStyle Minimized | Out-Null; }; for ($i = 0; $i -lt 15 -and -not $ok; $i++) { Start-Sleep -Seconds 2; try { Invoke-WebRequest -UseBasicParsing $url | Out-Null; $ok=$true } catch {} }; if ($ok) { Write-Host '[INFO] Qdrant is ready.'; Write-Host '[INFO] Qdrant storage: E:\mcp-index-data\qdrant\storage'; exit 0 } else { Write-Host '[ERROR] Qdrant could not be started after waiting for it to become reachable.'; exit 1 }"
if errorlevel 1 (
  call :log "ERROR: Qdrant is required for semantic search/indexing"
  pause
  exit /b 1
)
call :log "Qdrant readiness check completed"

call :log "Checking whether the search engine core needs a rebuild"
pushd "%SEARCH_ENGINE_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dist='%SEARCH_ENGINE_DIR%\dist\cli\run-core.js'; $mustBuild=$false; if (-not (Test-Path $dist)) { $mustBuild=$true } else { $distTime=(Get-Item $dist).LastWriteTimeUtc; $sources=Get-ChildItem '%SEARCH_ENGINE_DIR%\src' -Recurse -File -ErrorAction SilentlyContinue; $extra=@('%SEARCH_ENGINE_DIR%\package.json','%SEARCH_ENGINE_DIR%\package-lock.json','%SEARCH_ENGINE_DIR%\tsconfig.json'); foreach ($path in $extra) { if (Test-Path $path) { $sources += Get-Item $path } }; foreach ($item in $sources) { if ($item.LastWriteTimeUtc -gt $distTime) { $mustBuild=$true; break } } }; if ($mustBuild) { Write-Host '[INFO] Building search engine core...'; exit 10 } else { Write-Host '[INFO] Search engine core is up to date. Skipping build.'; exit 0 }"
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
if "%BUILD_EXIT_CODE%"=="10" (
  call :log "Building search engine core with npm run build"
  call npm run build
  if errorlevel 1 (
    call :log "ERROR: failed to build the search engine"
    popd
    pause
    exit /b 1
  )
  call :log "Search engine core build completed"
) else if not "%BUILD_EXIT_CODE%"=="0" (
  call :log "ERROR: failed while checking whether the search engine core needs a rebuild"
  popd
  pause
  exit /b 1
)
if "%BUILD_EXIT_CODE%"=="0" call :log "Search engine core is up to date"
popd

cd /d "%MCP_DIR%"
set "RESTART_DELAY_SECONDS=3"
set "SERVER_RESTART_COUNT=0"
:server_loop
set /a SERVER_RESTART_COUNT+=1
call :log "Launching Python MCP server (attempt %SERVER_RESTART_COUNT%)"
call :log Server command: %PYTHON_EXE% %MCP_DIR%\server.py --transport streamable-http --host %MCP_HOST% --port %MCP_PORT%
>>"%MCP_STDIO_LOG%" echo ============================================================
>>"%MCP_STDIO_LOG%" echo [%DATE% %TIME%] Launch attempt %SERVER_RESTART_COUNT%
>>"%MCP_STDIO_LOG%" echo Working directory: %MCP_DIR%
>>"%MCP_STDIO_LOG%" echo Python executable: %PYTHON_EXE%
>>"%MCP_STDIO_LOG%" echo Command: "%PYTHON_EXE%" "%MCP_DIR%\server.py" --transport streamable-http --host %MCP_HOST% --port %MCP_PORT%
where python >>"%MCP_STDIO_LOG%" 2>&1
"%PYTHON_EXE%" -V >>"%MCP_STDIO_LOG%" 2>&1
cmd /c "netstat -ano | findstr /R /C:":%MCP_PORT% .*LISTENING" /C:":%VSCODE_BRIDGE_PORT% .*LISTENING"" >>"%MCP_STDIO_LOG%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Continue'; & '%PYTHON_EXE%' '%MCP_DIR%\server.py' --transport streamable-http --host '%MCP_HOST%' --port '%MCP_PORT%' 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } | Tee-Object -FilePath '%MCP_STDIO_LOG%' -Append; $exitCode=$LASTEXITCODE; exit $exitCode"
set "SERVER_EXIT_CODE=%ERRORLEVEL%"
if "%SERVER_EXIT_CODE%"=="0" (
  call :log "Windows code search MCP stopped cleanly"
  pause
  exit /b 0
)
call :log "Windows code search MCP exited unexpectedly with code %SERVER_EXIT_CODE%"
call :log "Recent python stdio tail follows"
call :emit_tail "%MCP_STDIO_LOG%" 80
call :log "Recent runtime log tail follows"
call :emit_tail "%MCP_RUNTIME_LOG%" 80
if not defined RESTART_DELAY_SECONDS set "RESTART_DELAY_SECONDS=3"
call :log "Restarting Python MCP server in %RESTART_DELAY_SECONDS% seconds to preserve connector availability"
timeout /t %RESTART_DELAY_SECONDS% >nul
if not exist "%PYTHON_EXE%" (
  call :log "ERROR: python.exe disappeared before restart: %PYTHON_EXE%"
  pause
  exit /b %SERVER_EXIT_CODE%
)
goto server_loop



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

:detect_listener_pid
set "MCP_LISTENER_PID="
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:"%MCP_HOST%:%MCP_PORT% .*LISTENING"') do set "MCP_LISTENER_PID=%%I"
exit /b 0

:emit_tail
set "TAIL_PATH=%~1"
set "TAIL_COUNT=%~2"
if not exist "%TAIL_PATH%" (
  call :log "WARN: tail target does not exist: %TAIL_PATH%"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$path='%TAIL_PATH%'; $count=[int]'%TAIL_COUNT%'; Write-Host ('----- BEGIN TAIL: ' + $path + ' -----'); Get-Content -Path $path -Tail $count; Write-Host ('----- END TAIL: ' + $path + ' -----')"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$path='%TAIL_PATH%'; $count=[int]'%TAIL_COUNT%'; '----- BEGIN TAIL: ' + $path + ' -----' | Out-File -FilePath '%MCP_BOOT_LOG%' -Append -Encoding utf8; Get-Content -Path $path -Tail $count | Out-File -FilePath '%MCP_BOOT_LOG%' -Append -Encoding utf8; '----- END TAIL: ' + $path + ' -----' | Out-File -FilePath '%MCP_BOOT_LOG%' -Append -Encoding utf8"
set "TAIL_PATH="
set "TAIL_COUNT="
exit /b 0

:log
if not exist "%MCP_LOG_DIR%" mkdir "%MCP_LOG_DIR%" >nul 2>&1
set "LOG_TEXT=%*"
if defined LOG_TEXT if "!LOG_TEXT:~0,1!"=="\"" if "!LOG_TEXT:~-1!"=="\"" set "LOG_TEXT=!LOG_TEXT:~1,-1!"
set "LOG_LINE=[%DATE% %TIME%] !LOG_TEXT!"
echo(!LOG_LINE!
>>"%MCP_BOOT_LOG%" echo(!LOG_LINE!
set "LOG_TEXT="
set "LOG_LINE="
exit /b 0
