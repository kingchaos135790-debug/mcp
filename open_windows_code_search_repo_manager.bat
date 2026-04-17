@echo off
setlocal

set "MCP_DIR=E:\Program Files\mcp\windows-code-search-mcp"
set "WINDOWS_MCP_DIR=E:\Program Files\mcp\Windows-MCP"
set "INDEX_ROOT=E:\mcp-index-data"
set "AUTO_INDEX_CONFIG_PATH=%MCP_DIR%\managed-repositories.json"
set "PYTHON_CMD="

rem Change INDEX_ROOT above if you want search data stored somewhere else.
rem Keep it outside repos you watch/index to avoid self-triggered reindex loops.

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
