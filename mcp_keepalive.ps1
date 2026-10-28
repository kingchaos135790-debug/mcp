param(
    [switch]$Once,
    [switch]$FunctionsOnly
)

# Conservative terminal-bound supervisor. It never terminates live services:
# a failed HTTP check cannot establish process ownership.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root 'logs'
$LogFile = Join-Path $LogDir 'mcp-keepalive.log'
$ServerLauncher = Join-Path $Root 'launch_mcp_server.bat'
$NodeLauncher = Join-Path $Root 'launch_local_node.bat'
$TunnelLauncher = Join-Path $Root 'cloudflare.bat'
$ServerScript = Join-Path $Root 'windows-code-search-mcp\server.py'
$TunnelExe = Join-Path $Root 'cloudflare.exe'
$ConfigPath = Join-Path $Root 'mcp.paths.env'
$ServerUri = 'http://127.0.0.1:8000/'
$CheckIntervalSeconds = 15
$FailureThreshold = 2
$LaunchGraceSeconds = 300
$script:LastNodeLaunch = [datetime]::MinValue
$script:LastTunnelLaunch = [datetime]::MinValue
$script:LoggedDuplicateTunnel = $false

function Write-Log([string]$Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss.fff} {1}' -f (Get-Date), $Message
    Add-Content -LiteralPath $LogFile -Value $line
}

function Get-PublicBaseUrl {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return $null }
    $line = Get-Content -LiteralPath $ConfigPath |
        Where-Object { $_ -match '^OAUTH_BASE_URL=' } | Select-Object -First 1
    if (-not $line) { return $null }
    return $line.Substring('OAUTH_BASE_URL='.Length).Trim()
}

function Get-TunnelName {
    if (-not (Test-Path -LiteralPath $TunnelLauncher)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $TunnelLauncher)) {
        if ($line -match '^\s*set\s+"TUNNEL_NAME=([^"]+)"\s*$') {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Get-LocalNode {
    $path = Join-Path $Root 'windows-code-search-mcp\devices.json'
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $registry = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    $nodes = @($registry.devices | Where-Object { $_.enabled -eq $true -and $_.transport -eq 'local' })
    if ($nodes.Count -ne 1) { return $null }
    $node = $nodes[0]
    $port = [int]$node.local_forward_port
    if ($port -lt 1 -or $port -gt 65535 -or $port -ne [int]$node.remote_mcp_port -or $node.host -ne '127.0.0.1' -or $node.device_id -cnotmatch '^[a-z][a-z0-9_-]{0,23}$') { return $null }
    return $node
}

function Test-NodeEndpoint($Node) {
    try {
        $uri = 'http://127.0.0.1:{0}/__node_health' -f [int]$Node.local_forward_port
        $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        $identity = $response.Content | ConvertFrom-Json
        return ($response.StatusCode -eq 200 -and $identity.role -eq 'node' -and $identity.device_id -eq $Node.device_id)
    }
    catch { return $false }
}

function Get-NodeListeners($Node) {
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -eq [int]$Node.local_forward_port })
}

function Test-NodeProcess($Process, $Node) {
    if ($null -eq $Process -or $Process.Name -notmatch '^pythonw?\.exe$') { return $false }
    $cmd = [string]$Process.CommandLine
    $port = [regex]::Escape([string]$Node.local_forward_port)
    return ($cmd.IndexOf($ServerScript, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $cmd -match ('(?i)(?:^|\s)--port(?:=|\s+)' + $port + '(?:\s|$)') -and
        $cmd -match '(?i)(?:^|\s)--host(?:=|\s+)127\.0\.0\.1(?:\s|$)')
}

# Never log response bodies, request headers, URLs or raw exception messages:
# OAuth query strings and upstream responses can contain credentials.
function Get-HttpProbeResult([string]$Uri, [int]$TimeoutSeconds = 5) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $status = $null
    $transportError = 'none'
    try {
        $response = Invoke-WebRequest -Uri $Uri -Method Get -UseBasicParsing -MaximumRedirection 0 -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        $status = [int]$response.StatusCode
    }
    catch {
        $exception = $_.Exception
        if ($exception.Response) {
            try { $status = [int]$exception.Response.StatusCode }
            catch { $status = $null }
        }
        if ($null -eq $status) {
            # Log only exception type / WebExceptionStatus, never exception.Message.
            if ($exception -is [System.Net.WebException]) {
                $transportError = [string]$exception.Status
            }
            elseif ($exception.InnerException -is [System.Net.WebException]) {
                $transportError = [string]$exception.InnerException.Status
            }
            else {
                $transportError = $exception.GetType().Name
            }
        }
    }
    finally { $timer.Stop() }
    $healthy = ($null -ne $status -and $status -lt 500)
    $outcome = if ($null -ne $status) { "http-$status" } else { "transport-$transportError" }
    return [pscustomobject]@{
        Healthy = [bool]$healthy
        StatusCode = $status
        Outcome = $outcome
        ElapsedMs = [int]$timer.ElapsedMilliseconds
    }
}

function Test-HttpEndpoint([string]$Uri, [int]$TimeoutSeconds = 5) {
    return [bool](Get-HttpProbeResult $Uri $TimeoutSeconds).Healthy
}

function Format-HttpProbe($Probe) {
    if ($null -eq $Probe) { return 'probe=not-configured' }
    return "probe=$($Probe.Outcome) elapsedMs=$($Probe.ElapsedMs)"
}

function Format-ServiceOwners($Listeners, $Processes) {
    $ports = @($Listeners | ForEach-Object { '{0}:{1}/pid={2}' -f $_.LocalAddress, $_.LocalPort, $_.OwningProcess })
    $pids = @($Processes | ForEach-Object { $_.ProcessId })
    return "listeners=[$($ports -join ',')] managedPids=[$($pids -join ',')]"
}

# Do not trust process names alone. Confirm the exact executable/script and
# target port/tunnel; ambiguous or inaccessible process metadata fails closed.
function Test-ManagedServerProcess($Process) {
    if ($null -eq $Process -or $Process.Name -notmatch '^pythonw?\.exe$') { return $false }
    $cmd = [string]$Process.CommandLine
    return (
        $cmd.IndexOf($ServerScript, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $cmd -match '(?i)(?:^|\s)--port(?:=|\s+)8000(?:\s|$)' -and
        $cmd -match '(?i)(?:^|\s)--host(?:=|\s+)127\.0\.0\.1(?:\s|$)'
    )
}

function Test-ManagedTunnelProcess($Process, [string]$TunnelName) {
    if ($null -eq $Process -or -not $TunnelName -or $Process.Name -ne 'cloudflare.exe') { return $false }
    $exe = [string]$Process.ExecutablePath
    $cmd = [string]$Process.CommandLine
    if (-not $exe -or -not [string]::Equals($exe, $TunnelExe, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    return (
        $cmd -match '(?i)(?:^|\s)tunnel(?:\s|$)' -and
        $cmd -match ('(?i)(?:^|\s)run\s+["'']?' + [regex]::Escape($TunnelName) + '["'']?(?:\s|$)')
    )
}

function Get-ProcessesByName([string]$Name) {
    return @(Get-CimInstance Win32_Process -Filter "Name='$Name'" -ErrorAction Stop)
}

function Get-ServerListeners {
    # Query all listening sockets before filtering. Filtering by port in the
    # CIM query throws when the target port is absent; that is not an error.
    # Actual inspection errors still prevent an unsafe launch.
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -eq 8000 })
}

function Test-LauncherActive([string]$Launcher) {
    $processes = @(Get-ProcessesByName 'cmd.exe')
    foreach ($process in $processes) {
        if (([string]$process.CommandLine).IndexOf($Launcher, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }
    return $false
}

function Test-LaunchGrace([datetime]$LastLaunch) {
    return ((Get-Date) - $LastLaunch).TotalSeconds -lt $LaunchGraceSeconds
}

function Get-WatchdogAction([bool]$GatewayLauncherActive) {
    if (-not $GatewayLauncherActive) { return 'stop' }
    return 'monitor'
}

# Pure decisions are separately tested. No destructive action is returned.
function Get-ServerRecoveryAction(
    [bool]$Healthy, [int]$ListenerCount, [int]$ManagedCount,
    [bool]$LauncherActive, [bool]$RecentlyLaunched
) {
    if ($Healthy) { return 'healthy' }
    if ($ListenerCount -gt 0 -or $ManagedCount -gt 0) { return 'inspect' }
    if ($LauncherActive -or $RecentlyLaunched) { return 'startup-pending' }
    return 'start'
}

function Get-TunnelRecoveryAction(
    [bool]$PublicHealthy, [bool]$ServerHealthy, [int]$CandidateCount,
    [bool]$LauncherActive, [bool]$RecentlyLaunched
) {
    if ($PublicHealthy) { return 'healthy' }
    if (-not $ServerHealthy) { return 'startup-pending' }
    if ($CandidateCount -gt 0) { return 'inspect' }
    if ($LauncherActive -or $RecentlyLaunched) { return 'startup-pending' }
    return 'start'
}

function Start-Launcher([string]$Path) {
    # A terminal may close between the loop's first check and a recovery launch.
    if (-not (Test-LauncherActive $ServerLauncher)) {
        Write-Log 'gateway launcher closed before recovery; leaving services stopped'
        return $false
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Log "launcher missing: $Path"
        return $false
    }
    Write-Log "starting missing service using launcher: $Path"
    $process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/c', ('"' + $Path + '"')) -WorkingDirectory $Root -WindowStyle Hidden -PassThru -ErrorAction Stop
    Write-Log "launcher started, PID $($process.Id); allowing startup grace period"
    return $true
}

function Get-TunnelCandidates([string]$TunnelName) {
    if (-not $TunnelName) { return @() }
    $all = @(Get-ProcessesByName 'cloudflare.exe')
    $escaped = [regex]::Escape($TunnelName)
    # Include untrusted executables with the same tunnel name so we never
    # launch a duplicate. Only Test-ManagedTunnelProcess can mark one managed.
    return @($all | Where-Object {
        ([string]$_.CommandLine) -match ('(?i)(?:^|\s)run\s+["'']?' + $escaped + '["'']?(?:\s|$)')
    })
}

if ($FunctionsOnly) { return }

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\MCPGatewayKeepAlive', [ref]$createdNew)
if (-not $createdNew) {
    # Only one watchdog may coordinate launches on this machine.
    $mutex.Dispose()
    return
}

try {
    $publicBaseUrl = Get-PublicBaseUrl
    $tunnelName = Get-TunnelName
    $localNode = Get-LocalNode
    $serverFailures = 0
    $serverFailureStarted = $null
    $nodeFailures = 0
    $tunnelFailures = 0
    $tunnelFailureStarted = $null
    Write-Log "watchdog started (terminal-bound, non-destructive); tunnel configured=$([bool]$tunnelName); gateway probe=GET / (<500 means HTTP reachable)"
    if (-not $localNode) { Write-Log 'no single valid local node found; skipping local node recovery' }

    while ($true) {
        try {
            # The gateway launcher is the operator's on/off switch. A closed
            # terminal must never trigger an unattended gateway restart.
            if ((Get-WatchdogAction (Test-LauncherActive $ServerLauncher)) -eq 'stop') {
                Write-Log 'gateway launcher closed; stopping watchdog without restarting services'
                break
            }
            if ($localNode) {
                $nodeHealthy = Test-NodeEndpoint $localNode
                $nodeListeners = @(Get-NodeListeners $localNode)
                $nodeProcesses = @(Get-ProcessesByName 'python.exe' | Where-Object { Test-NodeProcess $_ $localNode })
                $nodeAction = Get-ServerRecoveryAction $nodeHealthy $nodeListeners.Count $nodeProcesses.Count (Test-LauncherActive $NodeLauncher) (Test-LaunchGrace $script:LastNodeLaunch)
                switch ($nodeAction) {
                    'healthy' { $nodeFailures = 0 }
                    'start' {
                        $nodeListeners = @(Get-NodeListeners $localNode)
                        $nodeProcesses = @(Get-ProcessesByName 'python.exe' | Where-Object { Test-NodeProcess $_ $localNode })
                        if ($nodeListeners.Count -eq 0 -and $nodeProcesses.Count -eq 0 -and -not (Test-LauncherActive $NodeLauncher)) {
                            $env:MCP_DEVICE_ID = [string]$localNode.device_id
                            $env:MCP_NODE_PORT = [string]$localNode.local_forward_port
                            $script:LastNodeLaunch = Get-Date
                            [void](Start-Launcher $NodeLauncher)
                        }
                        $nodeFailures = 0
                    }
                    'inspect' {
                        $nodeFailures++
                        if ($nodeFailures -eq $FailureThreshold -or $nodeFailures % 20 -eq 0) {
                            Write-Log "Local node unhealthy; failedProbes=$nodeFailures; $(Format-ServiceOwners $nodeListeners $nodeProcesses). Identity probe failed; refusing to kill or duplicate running services."
                        }
                    }
                    default { $nodeFailures = 0 }
                }
            }
            $serverProbe = Get-HttpProbeResult $ServerUri 5
            $serverHealthy = [bool]$serverProbe.Healthy
            $listeners = @(Get-ServerListeners)
            $servers = @(Get-ProcessesByName 'python.exe' | Where-Object { Test-ManagedServerProcess $_ })
            # The terminal was checked at the start of this cycle. The batch
            # file, not this watchdog, owns gateway restarts.
            $serverAction = Get-ServerRecoveryAction $serverHealthy $listeners.Count $servers.Count $false $false
            if ($serverAction -eq 'healthy') {
                if ($serverFailures -ge $FailureThreshold) {
                    $elapsed = [int]((Get-Date) - $serverFailureStarted).TotalSeconds
                    Write-Log "Gateway recovered after $elapsed seconds and $serverFailures failed probes; $(Format-HttpProbe $serverProbe)"
                }
                $serverFailures = 0
                $serverFailureStarted = $null
            }
            else {
                if ($serverFailures -eq 0) { $serverFailureStarted = Get-Date }
                $serverFailures++
            }

            switch ($serverAction) {
                'start' {
                    # The batch launcher owns Python restarts. Starting another
                    # launcher here would outlive an operator closing its window.
                    if ($serverFailures -eq $FailureThreshold -or $serverFailures % 20 -eq 0) {
                        Write-Log "Gateway listener absent; failedProbes=$serverFailures; $(Format-HttpProbe $serverProbe); $(Format-ServiceOwners $listeners $servers). Waiting for launcher restart loop."
                    }
                }
                'inspect' {
                    if ($serverFailures -eq $FailureThreshold -or $serverFailures % 20 -eq 0) {
                        Write-Log "MCP health failure; failedProbes=$serverFailures; $(Format-HttpProbe $serverProbe); $(Format-ServiceOwners $listeners $servers). Refusing to kill or duplicate running services."
                    }
                }
            }

            if ($tunnelName) {
                $candidates = @(Get-TunnelCandidates $tunnelName)
                if ($candidates.Count -gt 1 -and -not $script:LoggedDuplicateTunnel) {
                    Write-Log "multiple processes for the configured Cloudflare tunnel ($($candidates.Count)); leaving them untouched"
                    $script:LoggedDuplicateTunnel = $true
                }
                if ($candidates.Count -le 1) { $script:LoggedDuplicateTunnel = $false }
                # Without a public probe URL, process presence is the only
                # observable state. Do not label a present tunnel as unhealthy.
                $publicHealthy = ($candidates.Count -gt 0 -and -not $publicBaseUrl)
                $publicProbe = $null
                if ($publicBaseUrl) {
                    $publicProbe = Get-HttpProbeResult ($publicBaseUrl.TrimEnd('/') + '/') 8
                    $publicHealthy = [bool]$publicProbe.Healthy
                }
                # Public failures while the local server is down are not tunnel failures.
                $tunnelAction = Get-TunnelRecoveryAction $publicHealthy $serverHealthy $candidates.Count (Test-LauncherActive $TunnelLauncher) (Test-LaunchGrace $script:LastTunnelLaunch)
                if ($tunnelAction -eq 'healthy') {
                    if ($tunnelFailures -ge $FailureThreshold) {
                        $elapsed = [int]((Get-Date) - $tunnelFailureStarted).TotalSeconds
                        Write-Log "Public MCP recovered after $elapsed seconds and $tunnelFailures failed probes; $(Format-HttpProbe $publicProbe)"
                    }
                    $tunnelFailures = 0
                    $tunnelFailureStarted = $null
                }
                elseif ($tunnelAction -eq 'inspect') {
                    if ($tunnelFailures -eq 0) { $tunnelFailureStarted = Get-Date }
                }

                switch ($tunnelAction) {
                    'start' {
                        # Recheck the intended tunnel (including foreign binaries).
                        $candidates = @(Get-TunnelCandidates $tunnelName)
                        if ($candidates.Count -eq 0 -and -not (Test-LauncherActive $TunnelLauncher)) {
                            $script:LastTunnelLaunch = Get-Date
                            [void](Start-Launcher $TunnelLauncher)
                        }
                        $tunnelFailures = 0
                    }
                    'inspect' {
                        $tunnelFailures++
                        if ($tunnelFailures -eq $FailureThreshold -or $tunnelFailures % 20 -eq 0) {
                            $trusted = @($candidates | Where-Object { Test-ManagedTunnelProcess $_ $tunnelName })
                            Write-Log "Public MCP unhealthy; failedProbes=$tunnelFailures; local=$(Format-HttpProbe $serverProbe); public=$(Format-HttpProbe $publicProbe); tunnelCount=$($candidates.Count); managedTunnelCount=$($trusted.Count). Refusing to kill or duplicate an existing tunnel."
                        }
                    }
                    default { $tunnelFailures = 0 }
                }
            }
            elseif (-not $Once) {
                # No safe target identity; do not start an unknown tunnel.
                if ($tunnelFailures++ -eq 0) { Write-Log 'tunnel name not found in launcher; skipping tunnel management' }
            }
        }
        catch {
            Write-Log "health check or process inspection failed; skipping recovery this cycle: $($_.Exception.Message)"
        }

        if ($Once) { break }
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
}
finally {
    Write-Log 'watchdog stopped'
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
