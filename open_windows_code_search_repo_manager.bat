@echo off
setlocal

set "MCP_ROOT=%~dp0"
if "%MCP_ROOT:~-1%"=="\" set "MCP_ROOT=%MCP_ROOT:~0,-1%"
set "MCP_PATHS_FILE=%MCP_ROOT%\mcp.paths.env"
if not exist "%MCP_PATHS_FILE%" (
  echo ERROR: Shared path config not found: %MCP_PATHS_FILE%
  echo Copy mcp.paths.env.example to mcp.paths.env and edit the paths.
  pause
  exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%MCP_PATHS_FILE%") do set "%%A=%%B"
if not defined MCP_DIR (
  echo ERROR: MCP_DIR is missing from %MCP_PATHS_FILE%
  pause
  exit /b 1
)
if not defined WINDOWS_MCP_DIR (
  echo ERROR: WINDOWS_MCP_DIR is missing from %MCP_PATHS_FILE%
  pause
  exit /b 1
)
if not defined SEARCH_ENGINE_DIR (
  echo ERROR: SEARCH_ENGINE_DIR is missing from %MCP_PATHS_FILE%
  pause
  exit /b 1
)
if not defined INDEX_ROOT (
  echo ERROR: INDEX_ROOT is missing from %MCP_PATHS_FILE%
  pause
  exit /b 1
)
if not defined QDRANT_ROOT (
  echo ERROR: QDRANT_ROOT is missing from %MCP_PATHS_FILE%
  pause
  exit /b 1
)
for %%I in ("%MCP_ROOT%\%MCP_DIR%") do set "MCP_DIR=%%~fI"
for %%I in ("%MCP_ROOT%\%WINDOWS_MCP_DIR%") do set "WINDOWS_MCP_DIR=%%~fI"
for %%I in ("%MCP_ROOT%\%SEARCH_ENGINE_DIR%") do set "SEARCH_ENGINE_DIR=%%~fI"
for %%I in ("%MCP_ROOT%\%QDRANT_ROOT%") do set "QDRANT_ROOT=%%~fI"
set "QDRANT_START_BAT=%QDRANT_ROOT%\start-qdrant.bat"
set "QDRANT_URL=http://127.0.0.1:16333"
set "QDRANT_COLLECTION=code_chunks_bge_base_en_v1_5"
set "AUTO_INDEX_CONFIG_PATH=%MCP_DIR%\managed-repositories.json"
set "EMBEDDING_MODEL=Xenova/bge-base-en-v1.5"
set "EMBEDDING_DIMENSIONS=768"
set "EMBEDDING_CACHE_DIR=%INDEX_ROOT%\models"
set "EMBEDDING_BATCH_SIZE=16"
set "EMBEDDING_DEVICE=dml"
if "%NODE_USE_ENV_PROXY%"=="" set "NODE_USE_ENV_PROXY=1"
if "%HTTP_PROXY%"=="" set "HTTP_PROXY=http://127.0.0.1:7890"
if "%HTTPS_PROXY%"=="" set "HTTPS_PROXY=http://127.0.0.1:7890"
if "%NO_PROXY%"=="" set "NO_PROXY=127.0.0.1,localhost,::1"
set "PYTHON_CMD="

rem Shared paths are configured in mcp.paths.env.
rem Keep INDEX_ROOT outside watched repositories to avoid reindex loops.

if not exist "%MCP_DIR%\repo_manager.py" (
  echo ERROR: Repo manager not found:
  echo   %MCP_DIR%\repo_manager.py
  pause
  exit /b 1
)

if exist "%WINDOWS_MCP_DIR%\.venv\Scripts\python.exe" (
  "%WINDOWS_MCP_DIR%\.venv\Scripts\python.exe" -c "import tkinter" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD="%WINDOWS_MCP_DIR%\.venv\Scripts\python.exe""
)

if not defined PYTHON_CMD (
  py -3.12 -c "import tkinter" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)

if not defined PYTHON_CMD (
  py -3.11 -c "import tkinter" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3.11"
)

if not defined PYTHON_CMD (
  python -c "import tkinter" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo ERROR: No tkinter-enabled Python interpreter found.
  echo Tried:
  echo   %WINDOWS_MCP_DIR%\.venv\Scripts\python.exe
  echo   py -3.12
  echo   py -3.11
  echo   python
  pause
  exit /b 1
)

set "PYTHONPATH=%WINDOWS_MCP_DIR%\src;%MCP_DIR%"
call %PYTHON_CMD% "%MCP_DIR%\repo_manager.py"
