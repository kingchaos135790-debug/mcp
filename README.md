# MCP Workspace Notes

This workspace contains the root launcher scripts and local checkouts used to run the Windows MCP stack.

## PowerShell 5.1 Compatibility

The root launcher scripts in this folder target `powershell.exe` from Windows PowerShell 5.1, not PowerShell 7+.

Treat this as a PowerShell 5.1 versus PowerShell 7 API and behavior mismatch whenever you edit launcher code.

When editing the root launcher `.bat` files, keep these rules:

- Do not assume PowerShell 7 native-command behavior or newer APIs.
- Do not invoke a local executable by bare name from inside PowerShell. Resolve it to an absolute path first, for example `%~dp0cloudflare.exe`.
- When a native command is piped through `Tee-Object`, convert `ErrorRecord` objects back to plain text first. Without that step, PowerShell 5.1 can print normal stderr lines as `NativeCommandError` output.
- Preserve and return `$LASTEXITCODE` explicitly after the pipeline.

## Log Files

Root launcher logs are stored under `E:\Program Files\mcp\logs`.

- Each launcher run writes timestamped log files instead of reusing a single root-level `.log` file.
- Each log filename prefix is derived from the current launcher filename via `%~n0`, so renaming a root `.bat` changes future log names automatically.
- The retention count is controlled by `MCP_LOG_KEEP_COUNT`.
- If `MCP_LOG_KEEP_COUNT` is unset, the launcher uses its built-in fallback default.
- Multi-log launchers write matching launcher, stdio, and runtime logs for the same run timestamp.

Why this matters:

- PowerShell 5.1 does not behave like newer shells for native stderr handling.
- Invoking `tool.exe` by bare name from an embedded PowerShell command can fail even when the executable sits next to the `.bat` file.

Safe pattern for root launchers:

```bat
set "TOOL_EXE=%~dp0tool.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Continue'; & '%TOOL_EXE%' ... 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } | Tee-Object -FilePath '%LOG_PATH%' -Append; $exitCode=$LASTEXITCODE; exit $exitCode"
```

Use the same approach for Python launchers by replacing `'%TOOL_EXE%'` with the full Python executable path.

## Local secrets

Do not put OAuth client secrets directly in tracked launcher scripts.

Use `launch_mcp_server.local.bat` for local-only overrides such as `OAUTH_CLIENT_SECRET`.

- `launch_mcp_server.local.bat` is ignored by Git.
- `launch_mcp_server.bat` loads `launch_mcp_server.local.bat` automatically when it exists.
- `launch_mcp_server.local.example.bat` shows the expected format for local overrides.
