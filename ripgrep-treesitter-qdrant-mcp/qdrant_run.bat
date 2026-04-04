@echo off
setlocal

rem Portable launcher: copy this .bat into any repo folder and run it there.
rem By default it indexes the folder where this .bat lives.
rem Optional usage:
rem   index-this-folder.bat
rem   index-this-folder.bat "C:\path\to\repo"

set "MCP_ROOT=E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp"
set "QDRANT_ROOT=E:\Program Files\qdrant"
set "QDRANT_EXE=%QDRANT_ROOT%\qdrant.exe"
set "QDRANT_START_BAT=%QDRANT_ROOT%\start-qdrant.bat"
set "QDRANT_CONFIG_PATH=%QDRANT_ROOT%\config\local.yaml"
set "QDRANT_URL=http://127.0.0.1:16333"
set "QDRANT_COLLECTION=code_chunks"
set "INDEX_ROOT=E:\mcp-index-data"

if not exist "%MCP_ROOT%\package.json" (
  echo [ERROR] MCP project not found at:
  echo         %MCP_ROOT%
  exit /b 1
)

if not exist "%QDRANT_EXE%" (
  echo [ERROR] Qdrant not found at:
  echo         %QDRANT_EXE%
  exit /b 1
)

if not exist "%QDRANT_CONFIG_PATH%" (
  echo [ERROR] Qdrant config not found at:
  echo         %QDRANT_CONFIG_PATH%
  exit /b 1
)

if not exist "%QDRANT_START_BAT%" (
  echo [ERROR] Qdrant launcher not found at:
  echo         %QDRANT_START_BAT%
  exit /b 1
)

if "%~1"=="" (
  set "REPO_ROOT=%~dp0"
) else (
  set "REPO_ROOT=%~1"
)

for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] MCP root : %MCP_ROOT%
echo [INFO] Qdrant   : %QDRANT_URL%
echo [INFO] Index dir: %INDEX_ROOT%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok=$false; try { Invoke-WebRequest -UseBasicParsing '%QDRANT_URL%/collections' | Out-Null; $ok=$true } catch {}; if (-not $ok) { Start-Process -FilePath '%QDRANT_START_BAT%' -WorkingDirectory '%QDRANT_ROOT%' -WindowStyle Minimized; Start-Sleep -Seconds 4; try { Invoke-WebRequest -UseBasicParsing '%QDRANT_URL%/collections' | Out-Null; $ok=$true } catch {} }; if ($ok) { Write-Host '[INFO] Qdrant is ready.'; Write-Host '[INFO] Qdrant storage: E:\mcp-index-data\qdrant\storage'; exit 0 } else { Write-Host '[ERROR] Qdrant could not be started.'; exit 1 }"
if errorlevel 1 exit /b 1

pushd "%MCP_ROOT%"
set "QDRANT_URL=%QDRANT_URL%"
set "QDRANT_COLLECTION=%QDRANT_COLLECTION%"
set "INDEX_ROOT=%INDEX_ROOT%"
set "REPO_ROOT=%REPO_ROOT%"

call npm run index -- "%REPO_ROOT%"
set "EXITCODE=%ERRORLEVEL%"
popd

if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] Indexing failed with exit code %EXITCODE%.
  exit /b %EXITCODE%
)

echo.
echo [OK] Indexing complete.
echo [INFO] Semantic index: Qdrant collection %QDRANT_COLLECTION%
echo [INFO] Lexical index : %INDEX_ROOT%\local-lexical-index.json
endlocal
exit /b 0
