# AGENTS.md

## Root Workspace Rule

The root launcher scripts in `E:\Program Files\mcp` run through Windows PowerShell 5.1.

Do not edit these launchers as if they run on PowerShell 7+.

Assume a PowerShell 5.1 versus PowerShell 7 API and behavior mismatch when changing root launchers.

## Required Compatibility Rules

- Use absolute executable paths such as `%~dp0cloudflare.exe` or `%PYTHON_EXE%` before crossing from `.bat` into PowerShell.
- Do not rely on bare `tool.exe` resolution from embedded PowerShell commands.
- If a native command is piped to `Tee-Object`, normalize `System.Management.Automation.ErrorRecord` values back to plain text first.
- Capture `$LASTEXITCODE` after the pipeline and `exit $exitCode` so the batch file gets the real native process exit code.

## Root Log Rules

- Store root launcher logs under `E:\Program Files\mcp\logs`, not directly in the workspace root.
- Use timestamped per-run log filenames so multiple runs keep separate artifacts.
- Derive the log filename prefix from the current `.bat` filename, typically via `%~n0`, so renames propagate automatically.
- Honor `MCP_LOG_KEEP_COUNT` for retention, with a reasonable default only when the variable is unset.
- For multi-log launchers, keep the same run timestamp across related files so one run can be correlated easily.

## Safe PowerShell Pattern

```powershell
$ErrorActionPreference = 'Continue'
& $exe @args 2>&1 |
  ForEach-Object {
    if ($_ -is [System.Management.Automation.ErrorRecord]) {
      $_.Exception.Message
    } else {
      $_
    }
  } |
  Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE
exit $exitCode
```

## Why

PowerShell 5.1 can surface normal native stderr as `NativeCommandError` formatting, and local executable lookup does not always match `cmd.exe` expectations.
