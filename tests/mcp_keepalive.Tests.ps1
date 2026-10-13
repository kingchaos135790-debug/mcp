# Run with: powershell.exe -NoProfile -Command "Invoke-Pester .\tests\mcp_keepalive.Tests.ps1"
# -FunctionsOnly must not create a mutex, inspect live processes or start services.
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'mcp_keepalive.ps1') -FunctionsOnly

Describe 'MCP keepalive safety and identity checks' {
    It 'does not restart an unresponsive server while a listener exists' {
        (Get-ServerRecoveryAction $false 1 0 $false $false) | Should Be 'inspect'
    }

    It 'does not restart a recognized running server despite a failed health check' {
        (Get-ServerRecoveryAction $false 0 1 $false $false) | Should Be 'inspect'
    }

    It 'does not launch when an existing launcher or startup grace is present' {
        (Get-ServerRecoveryAction $false 0 0 $true $false) | Should Be 'startup-pending'
        (Get-ServerRecoveryAction $false 0 0 $false $true) | Should Be 'startup-pending'
    }

    It 'only starts a server that is definitively absent' {
        (Get-ServerRecoveryAction $false 0 0 $false $false) | Should Be 'start'
        (Get-ServerRecoveryAction $true 0 0 $false $false) | Should Be 'healthy'
    }

    It 'does not restart or duplicate any existing tunnel after an HTTP failure' {
        (Get-TunnelRecoveryAction $false $true 1 $false $false) | Should Be 'inspect'
        (Get-TunnelRecoveryAction $false $true 2 $false $false) | Should Be 'inspect'
    }

    It 'does not start or diagnose a tunnel while the local MCP server is down' {
        (Get-TunnelRecoveryAction $false $false 0 $false $false) | Should Be 'startup-pending'
        (Get-TunnelRecoveryAction $false $false 2 $false $false) | Should Be 'startup-pending'
    }

    It 'does not duplicate a tunnel during startup or when the public endpoint is healthy' {
        (Get-TunnelRecoveryAction $false $true 0 $true $false) | Should Be 'startup-pending'
        (Get-TunnelRecoveryAction $false $true 0 $false $true) | Should Be 'startup-pending'
        (Get-TunnelRecoveryAction $true $true 0 $false $false) | Should Be 'healthy'
    }

    It 'can start a missing tunnel if the local service is healthy' {
        (Get-TunnelRecoveryAction $false $true 0 $false $false) | Should Be 'start'
    }

    It 'identifies the managed server script and exact listening options' {
        $p = [pscustomobject]@{
            Name = 'python.exe'
            CommandLine = ('"C:\Python\python.exe" "' + $ServerScript + '" --transport streamable-http --host 127.0.0.1 --port 8000')
        }
        (Test-ManagedServerProcess $p) | Should Be $true
        $p.CommandLine = '"C:\Python\python.exe" C:\other\server.py --host 127.0.0.1 --port 8000'
        (Test-ManagedServerProcess $p) | Should Be $false
        $p.CommandLine = ('"C:\Python\python.exe" "' + $ServerScript + '" --host 127.0.0.1 --port 9000')
        (Test-ManagedServerProcess $p) | Should Be $false
    }

    It 'recognizes only the expected Cloudflare executable and named tunnel' {
        $p = [pscustomobject]@{
            Name = 'cloudflare.exe'
            ExecutablePath = $TunnelExe
            CommandLine = ('"' + $TunnelExe + '" tunnel --protocol http2 run my-tunnel')
        }
        (Test-ManagedTunnelProcess $p 'my-tunnel') | Should Be $true
        (Test-ManagedTunnelProcess $p 'another-tunnel') | Should Be $false
        $p.ExecutablePath = 'C:\other\cloudflare.exe'
        (Test-ManagedTunnelProcess $p 'my-tunnel') | Should Be $false
        $p.ExecutablePath = $null
        (Test-ManagedTunnelProcess $p 'my-tunnel') | Should Be $false
    }

    It 'detects foreign executables targeting the same named tunnel and avoids duplicates' {
        $foreign = [pscustomobject]@{
            Name = 'cloudflare.exe'
            ExecutablePath = 'C:\other\cloudflare.exe'
            CommandLine = 'C:\other\cloudflare.exe tunnel run my-tunnel'
        }
        Mock Get-ProcessesByName { return @($foreign) }
        $found = @(Get-TunnelCandidates 'my-tunnel')
        $found.Count | Should Be 1
        (Test-ManagedTunnelProcess $found[0] 'my-tunnel') | Should Be $false
    }

    It 'returns no tunnel candidates when the name is unknown' {
        @(Get-TunnelCandidates '').Count | Should Be 0
    }

    It 'enforces a cooldown after any launcher attempt' {
        (Test-LaunchGrace (Get-Date)) | Should Be $true
        (Test-LaunchGrace ((Get-Date).AddMinutes(-6))) | Should Be $false
    }

    It 'contains no process-termination commands' {
        $source = Get-Content -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'mcp_keepalive.ps1') -Raw
        $source | Should Not Match '(?m)^\s*(?:Stop-Process|Stop-Service|taskkill(?:\.exe)?)\b'
    }
}
