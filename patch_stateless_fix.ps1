$ErrorActionPreference = 'Stop'
$serverPath = 'E:\Program Files\mcp\windows-code-search-mcp\server.py'
$launcherPath = 'E:\Program Files\mcp\launch_mcp_server.bat'

$serverText = [System.IO.File]::ReadAllText($serverPath)
$serverOld = '    fastmcp.settings.set_setting("stateless_http", True)'
$serverNew = "    stateless_http = os.getenv(\"FASTMCP_STATELESS_HTTP\", \"\").strip().lower() in {\"1\", \"true\", \"yes\", \"on\"}`r`n    fastmcp.settings.set_setting(\"stateless_http\", stateless_http)"
if (-not $serverText.Contains($serverOld)) { throw 'server.py target text not found' }
$serverText = $serverText.Replace($serverOld, $serverNew)
[System.IO.File]::WriteAllText($serverPath, $serverText, [System.Text.UTF8Encoding]::new($false))

$launcherText = [System.IO.File]::ReadAllText($launcherPath)
$launcherOldLog = 'call :log "HTTP session mode: stateless"'
$launcherNewLog = "if \"%FASTMCP_STATELESS_HTTP%\"==\"\" set \"FASTMCP_STATELESS_HTTP=false\"`r`ncall :log \"HTTP session mode: %FASTMCP_STATELESS_HTTP%\""
if (-not $launcherText.Contains($launcherOldLog)) { throw 'launch_mcp_server.bat log target text not found' }
$launcherText = $launcherText.Replace($launcherOldLog, $launcherNewLog)
$launcherOldEnv = 'set "FASTMCP_STATELESS_HTTP=true"'
$launcherNewEnv = 'set "FASTMCP_STATELESS_HTTP=%FASTMCP_STATELESS_HTTP%"'
if (-not $launcherText.Contains($launcherOldEnv)) { throw 'launch_mcp_server.bat env target text not found' }
$launcherText = $launcherText.Replace($launcherOldEnv, $launcherNewEnv)
[System.IO.File]::WriteAllText($launcherPath, $launcherText, [System.Text.UTF8Encoding]::new($false))

Write-Output 'OK'
