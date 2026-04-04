@echo off
setlocal

set "MCP_DIR=E:\Program Files\mcp\windows-code-search-mcp"
set "WINDOWS_MCP_DIR=E:\Program Files\mcp\Windows-MCP"
set "INDEX_ROOT=E:\mcp-index-data"
set "PYTHON_EXE=%WINDOWS_MCP_DIR%\.venv\Scripts\python.exe"
set "AUTO_INDEX_CONFIG_PATH=%MCP_DIR%\managed-repositories.json"

rem Change INDEX_ROOT above if you want search data stored somewhere else.
rem Keep it outside repos you watch/index to avoid self-triggered reindex loops.

if not exist "%MCP_DIR%\repo_manager.py" (
  echo ERROR: Repo manager not found:
  echo   %MCP_DIR%\repo_manager.py
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo ERROR: python.exe not found:
  echo   %PYTHON_EXE%
  pause
  exit /b 1
)

set "PYTHONPATH=%WINDOWS_MCP_DIR%\src;%MCP_DIR%"
"%PYTHON_EXE%" "%MCP_DIR%\repo_manager.py"
