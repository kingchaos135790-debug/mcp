param(
    [switch]$Once,
    [switch]$FunctionsOnly
)

# Conservative gateway supervisor. This script starts missing services but never
# terminates live processes: a failed HTTP check cannot establish process ownership.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root 'logs'
$LogFile = Join-Path $LogDir 'mcp-keepalive.log'
$ServerLauncher = Join-Path $Root 'launch_mcp_server.bat'
$TunnelLauncher = Join-Path $Root 'cloudflare.bat'
$ServerScript = Join-Path $Root 'windows-code-search-mcp\server.py'
$TunnelExe = Join-Path $Root 'cloudflare.exe'
$ConfigPath = Join-Path $Root 'mcp.paths.env'
$ServerUri = 'http://127.0.0.1:8000/'
$CheckIntervalSeconds = 15
$FailureThreshold = 2
$LaunchGraceSeconds = 300
$script:LastServerLaunch = [datetime]::MinValue
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

function Test-HttpEndpoint([string]$Uri, [int]$TimeoutSeconds = 5) {
    try {
        $response = Invoke-WebRequest -Uri $Uri -Method Get -UseBasicParsing -MaximumRedirection 0 -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        return ([int]$response.StatusCode -lt 500)
    }
    catch {
        if ($_.Exception.Response) {
            try { return ([int]$_.Exception.Response.StatusCode -lt 500) }
            catch { return $false }
        }
        return $false
    }
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
    $serverFailures = 0
    $tunnelFailures = 0
    Write-Log "watchdog started (non-destructive); tunnel configured=$([bool]$tunnelName)"

    while ($true) {
        try {
            $serverHealthy = Test-HttpEndpoint $ServerUri 5
            $listeners = @(Get-ServerListeners)
            $servers = @(Get-ProcessesByName 'python.exe' | Where-Object { Test-ManagedServerProcess $_ })
            $serverAction = Get-ServerRecoveryAction $serverHealthy $listeners.Count $servers.Count (Test-LauncherActive $ServerLauncher) (Test-LaunchGrace $script:LastServerLaunch)

            switch ($serverAction) {
                'healthy' { $serverFailures = 0 }
                'start' {
                    # Double-check immediately before launch: another operator
                    # could have started a listener during the health probe.
                    $listeners = @(Get-ServerListeners)
                    $servers = @(Get-ProcessesByName 'python.exe' | Where-Object { Test-ManagedServerProcess $_ })
                    if ($listeners.Count -eq 0 -and $servers.Count -eq 0 -and -not (Test-LauncherActive $ServerLauncher)) {
                        $script:LastServerLaunch = Get-Date
                        [void](Start-Launcher $ServerLauncher)
                    }
                    $serverFailures = 0
                }
                'inspect' {
                    $serverFailures++
                    if ($serverFailures -eq $FailureThreshold -or $serverFailures % 20 -eq 0) {
                        Write-Log "MCP health failure; listener count=$($listeners.Count), known server count=$($servers.Count). Refusing to kill or duplicate running services."
                    }
                }
                default { $serverFailures = 0 }
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
                if ($publicBaseUrl) {
                    $publicHealthy = Test-HttpEndpoint ($publicBaseUrl.TrimEnd('/') + '/') 8
                }
                # Public failures while the local server is down are not tunnel failures.
                $tunnelAction = Get-TunnelRecoveryAction $publicHealthy $serverHealthy $candidates.Count (Test-LauncherActive $TunnelLauncher) (Test-LaunchGrace $script:LastTunnelLaunch)

                switch ($tunnelAction) {
                    'healthy' { $tunnelFailures = 0 }
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
                            Write-Log "Public MCP unhealthy; tunnel count=$($candidates.Count), matched executable count=$($trusted.Count). Refusing to kill or duplicate an existing tunnel."
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
