param(
    [Parameter(Mandatory=$true)][ValidateSet('node','gateway')][string]$Role,
    [string]$DeviceId = $env:MCP_DEVICE_ID,
    [string]$DevicesPath = $env:MCP_DEVICES_PATH,
    [string]$BindHost = '127.0.0.1',
    [int]$Port = 18000,
    [string]$PythonExe = $env:PYTHON_EXE,
    [string]$LogPrefix = 'launch_distributed',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = Split-Path -Parent $projectRoot
if (-not $PythonExe) { $PythonExe = Join-Path $repoRoot 'Windows-MCP\.venv\Scripts\python.exe' }
$PythonExe = [System.IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python executable not found: $PythonExe" }
if ($LogPrefix -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid log prefix' }
$env:MCP_ROLE = $Role
if ($DeviceId) { $env:MCP_DEVICE_ID = $DeviceId }
if ($DevicesPath) { $env:MCP_DEVICES_PATH = [System.IO.Path]::GetFullPath($DevicesPath) }
if (-not $env:WINDOWS_MCP_DIR) { $env:WINDOWS_MCP_DIR = Join-Path $repoRoot 'Windows-MCP' }
if (-not $env:SEARCH_ENGINE_DIR) { $env:SEARCH_ENGINE_DIR = Join-Path $repoRoot 'ripgrep-treesitter-qdrant-mcp' }
if ($Role -eq 'node') {
    $env:OAUTH_ENABLED = 'false'
    if (-not $env:INDEX_ROOT) { $env:INDEX_ROOT = Join-Path $env:LOCALAPPDATA 'windows-code-search-mcp\indexes' }
}
$env:PYTHONUNBUFFERED = '1'
$env:MCP_LOG_DIR = Join-Path $repoRoot 'logs'
$null = New-Item -ItemType Directory -Force -Path $env:MCP_LOG_DIR
if (-not $env:MCP_LOG_KEEP_COUNT) { $env:MCP_LOG_KEEP_COUNT = '3' }
$keepCount = 0
if (-not [int]::TryParse($env:MCP_LOG_KEEP_COUNT, [ref]$keepCount) -or $keepCount -lt 1) { throw 'MCP_LOG_KEEP_COUNT must be a positive integer' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdioLog = Join-Path $env:MCP_LOG_DIR "$LogPrefix-stdio-$stamp.log"
$env:MCP_RUNTIME_LOG = Join-Path $env:MCP_LOG_DIR "$LogPrefix-runtime-$stamp.log"
foreach ($kind in @('stdio','runtime')) {
    Get-ChildItem -LiteralPath $env:MCP_LOG_DIR -Filter "$LogPrefix-$kind-*.log" |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip ($keepCount - 1) |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}
Set-Location -LiteralPath $projectRoot
$ErrorActionPreference = 'Continue'
& $PythonExe -m distributed.preflight --role $Role --host $BindHost --port $Port 2>&1 |
    ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } |
    Tee-Object -FilePath $stdioLog -Append
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0 -or $CheckOnly) { exit $exitCode }
& $PythonExe (Join-Path $projectRoot 'server.py') --transport streamable-http --host $BindHost --port $Port 2>&1 |
    ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } |
    Tee-Object -FilePath $stdioLog -Append
$exitCode = $LASTEXITCODE
exit $exitCode
