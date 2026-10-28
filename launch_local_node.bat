@echo off
setlocal EnableExtensions
set "MCP_ROOT=%~dp0"
set "MCP_PATHS_FILE=%MCP_ROOT%mcp.paths.env"
if not exist "%MCP_PATHS_FILE%" exit /b 1
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%MCP_PATHS_FILE%") do set "%%A=%%B"
if not defined MCP_DIR exit /b 1
if not defined WINDOWS_MCP_DIR exit /b 1
if not defined SEARCH_ENGINE_DIR exit /b 1
if not defined INDEX_ROOT exit /b 1
if not defined MCP_DEVICE_ID exit /b 1
if not defined MCP_NODE_PORT exit /b 1
for %%I in ("%MCP_ROOT%%MCP_DIR%") do set "MCP_DIR=%%~fI"
for %%I in ("%MCP_ROOT%%WINDOWS_MCP_DIR%") do set "WINDOWS_MCP_DIR=%%~fI"
for %%I in ("%MCP_ROOT%%SEARCH_ENGINE_DIR%") do set "SEARCH_ENGINE_DIR=%%~fI"
set "PYTHON_EXE=%WINDOWS_MCP_DIR%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" exit /b 1
set "AUTO_INDEX_CONFIG_PATH=%MCP_DIR%\managed-repositories.json"
set "MCP_DEVICES_PATH=%MCP_DIR%\devices.json"
set "PYTHONPATH=%WINDOWS_MCP_DIR%\src;%MCP_DIR%"
call "%MCP_DIR%\launch_node.bat" -DeviceId "%MCP_DEVICE_ID%" -Port %MCP_NODE_PORT% -PythonExe "%PYTHON_EXE%" -LogPrefix "%~n0"
exit /b %ERRORLEVEL%
