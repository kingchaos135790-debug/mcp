# Run with: powershell.exe -NoProfile -Command "Invoke-Pester .\tests\mcp_keepalive.Tests.ps1"
# -FunctionsOnly must not create a mutex, inspect live processes or start services.
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'mcp_keepalive.ps1') -FunctionsOnly

Describe 'MCP keepalive safety and identity checks' {
    It 'stops monitoring when the gateway launcher terminal is gone' {
        (Get-WatchdogAction $false) | Should Be 'stop'
        (Get-WatchdogAction $true) | Should Be 'monitor'
    }

    It 'does not launch a node if the gateway terminal closes mid-cycle' {
        Mock Test-LauncherActive { $false }
        Mock Write-Log { }
        Mock Start-Process { throw 'Must not start a detached service' }
        (Start-Launcher $NodeLauncher) | Should Be $false
        Assert-MockCalled Start-Process -Times 0
    }
    It 'reports an HTTP 404 response as a reachable server with explicit status' {
        Mock Invoke-WebRequest { [pscustomobject]@{ StatusCode = 404 } }
        $probe = Get-HttpProbeResult 'http://127.0.0.1:8000/' 2
        $probe.Healthy | Should Be $true
        $probe.Outcome | Should Be 'http-404'
        $probe.ElapsedMs | Should BeOfType [int]
    }

    It 'reports an HTTP 503 as a failed application response' {
        Mock Invoke-WebRequest { [pscustomobject]@{ StatusCode = 503 } }
        $probe = Get-HttpProbeResult 'http://127.0.0.1:8000/' 2
        $probe.Healthy | Should Be $false
        $probe.Outcome | Should Be 'http-503'
    }

    It 'reports a transport timeout without logging raw exception text' {
        Mock Invoke-WebRequest { throw [System.Net.WebException]::new('secret must not leak', [System.Net.WebExceptionStatus]::Timeout) }
        $probe = Get-HttpProbeResult 'http://127.0.0.1:8000/' 2
        $probe.Healthy | Should Be $false
        $probe.Outcome | Should Be 'transport-Timeout'
        (Format-HttpProbe $probe) | Should Not Match 'secret'
    }

    It 'includes socket addresses and owning PIDs but not process command lines' {
        $listeners = @([pscustomobject]@{ LocalAddress = '127.0.0.1'; LocalPort = 8000; OwningProcess = 1234 })
        $processes = @([pscustomobject]@{ ProcessId = 1234; CommandLine = 'secret=private' })
        $diagnostic = Format-ServiceOwners $listeners $processes
        $diagnostic | Should Match '127.0.0.1:8000/pid=1234'
        $diagnostic | Should Match 'managedPids=\[1234\]'
        $diagnostic | Should Not Match 'secret'
    }

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

    It 'loads the one enabled local node and its configured loopback port' {
        Mock Test-Path { $true }
        Mock Get-Content { '{"devices":[{"device_id":"host_node","enabled":true,"transport":"local","host":"127.0.0.1","local_forward_port":18001,"remote_mcp_port":18001}]}' }
        $node = Get-LocalNode
        $node.device_id | Should Be 'host_node'
        $node.local_forward_port | Should Be 18001
    }

    It 'recognizes only the exact local node script and port' {
        $node = [pscustomobject]@{ local_forward_port = 18001 }
        $p = [pscustomobject]@{
            Name = 'python.exe'
            CommandLine = ('"C:\Python\python.exe" "' + $ServerScript + '" --host 127.0.0.1 --port 18001')
        }
        (Test-NodeProcess $p $node) | Should Be $true
        $p.CommandLine = $p.CommandLine.Replace('18001', '8000')
        (Test-NodeProcess $p $node) | Should Be $false
        $p.CommandLine = 'python.exe C:\other\server.py --host 127.0.0.1 --port 18001'
        (Test-NodeProcess $p $node) | Should Be $false
    }

    It 'requires the local node health response to match the configured identity' {
        $node = [pscustomobject]@{ local_forward_port = 18001; device_id = 'host_node' }
        Mock Invoke-WebRequest { [pscustomobject]@{ StatusCode = 200; Content = '{"role":"node","device_id":"host_node"}' } }
        (Test-NodeEndpoint $node) | Should Be $true
        Mock Invoke-WebRequest { [pscustomobject]@{ StatusCode = 200; Content = '{"role":"gateway","device_id":"host_node"}' } }
        (Test-NodeEndpoint $node) | Should Be $false
    }

    It 'refuses to duplicate a local node with a listener, process, launcher or recent launch' {
        (Get-ServerRecoveryAction $false 1 0 $false $false) | Should Be 'inspect'
        (Get-ServerRecoveryAction $false 0 1 $false $false) | Should Be 'inspect'
        (Get-ServerRecoveryAction $false 0 0 $true $false) | Should Be 'startup-pending'
        (Get-ServerRecoveryAction $false 0 0 $false $true) | Should Be 'startup-pending'
        (Get-ServerRecoveryAction $false 0 0 $false $false) | Should Be 'start'
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
