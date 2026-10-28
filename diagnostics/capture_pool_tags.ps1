# Read-only kernel pool snapshot for Windows PowerShell 5.1.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\diagnostics\capture_pool_tags.ps1
param([int]$Top = 15, [switch]$ConsoleOnly)

$ErrorActionPreference = 'Stop'
$source = @'
using System;
using System.Runtime.InteropServices;

public static class McpPoolTagNative
{
    [DllImport("ntdll.dll")]
    public static extern int NtQuerySystemInformation(
        int informationClass, IntPtr buffer, int length, out int returnLength);
}
'@
Add-Type -TypeDefinition $source -ErrorAction Stop

function Get-PoolTags {
    $size = 262144
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        if ($size -gt 16777216) { throw 'Pool tag data exceeds 16 MB limit.' }
        $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
        try {
            [int]$returned = 0
            $status = [McpPoolTagNative]::NtQuerySystemInformation(
                22, $buffer, $size, [ref]$returned)
            if ($status -eq -1073741820) {
                $size = [Math]::Max($size * 2, $returned + 65536)
                continue
            }
            if ($status -ne 0) {
                throw ('Pool tag query failed, NTSTATUS ' + $status.ToString('X8'))
            }
            $count = [Runtime.InteropServices.Marshal]::ReadInt32($buffer, 0)
            if ($count -lt 0 -or $count -gt 100000) {
                throw ('Unexpected pool tag count: ' + $count)
            }
            $rows = for ($i = 0; $i -lt $count; $i++) {
                $at = [IntPtr]::Add($buffer, 8 + $i * 40)
                $tagBytes = [BitConverter]::GetBytes(
                    [Runtime.InteropServices.Marshal]::ReadInt32($at, 0))
                $tag = [Text.Encoding]::ASCII.GetString($tagBytes) -replace '[^\x20-\x7E]', '?'
                $pagedAllocs = [Runtime.InteropServices.Marshal]::ReadInt32($at, 4)
                $pagedFrees = [Runtime.InteropServices.Marshal]::ReadInt32($at, 8)
                $nonpagedAllocs = [Runtime.InteropServices.Marshal]::ReadInt32($at, 24)
                $nonpagedFrees = [Runtime.InteropServices.Marshal]::ReadInt32($at, 28)
                [pscustomobject]@{
                    Tag = $tag
                    PagedBytes = [Runtime.InteropServices.Marshal]::ReadInt64($at, 16)
                    NonpagedBytes = [Runtime.InteropServices.Marshal]::ReadInt64($at, 32)
                    PagedOutstanding = [long]$pagedAllocs - $pagedFrees
                    NonpagedOutstanding = [long]$nonpagedAllocs - $nonpagedFrees
                }
            }
            return $rows
        }
        finally {
            [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)
        }
    }
    throw 'Pool tag query did not complete.'
}

$capturedAt = Get-Date
$rows = @(Get-PoolTags)
$perf = Get-Counter '\Memory\Committed Bytes',
    '\Memory\Commit Limit',
    '\Memory\Pool Paged Bytes',
    '\Memory\Pool Nonpaged Bytes' -ErrorAction Stop

$counter = @{}
foreach ($sample in $perf.CounterSamples) {
    $label = ($sample.Path -split '\\')[-1]
    $counter[$label] = [math]::Round($sample.CookedValue / 1MB, 1)
}
$summary = [pscustomobject]@{
    RecordedAt = $capturedAt.ToString('o')
    BootAt = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')
    CommittedMB = $counter['committed bytes']
    CommitLimitMB = $counter['commit limit']
    PagedPoolMB = $counter['pool paged bytes']
    NonpagedPoolMB = $counter['pool nonpaged bytes']
    TagCount = $rows.Count
}

if (-not $ConsoleOnly) {
    $logDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\pool-snapshots'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stamp = $capturedAt.ToString('yyyyMMdd-HHmmss-fff')
    $tagsPath = Join-Path $logDir ("pool-tags-$stamp.csv")
    $summaryPath = Join-Path $logDir 'pool-summary.csv'
    $rows | Export-Csv -LiteralPath $tagsPath -NoTypeInformation -Encoding UTF8
    # Track private bytes by PID to distinguish a user-process leak from a driver leak.
    $processesPath = Join-Path $logDir ("processes-$stamp.csv")
    Get-Process -ErrorAction Stop |
        Select-Object ProcessName, Id, PrivateMemorySize64, WorkingSet64, HandleCount |
        Export-Csv -LiteralPath $processesPath -NoTypeInformation -Encoding UTF8
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        $summary | Export-Csv -LiteralPath $summaryPath -NoTypeInformation -Encoding UTF8
    }
    else {
        $summary | ConvertTo-Csv -NoTypeInformation | Select-Object -Skip 1 |
            Add-Content -LiteralPath $summaryPath -Encoding UTF8
    }
    Write-Output "Saved: $tagsPath"
    Write-Output "Summary history: $summaryPath"
}

$summary | Format-List | Out-String | Write-Output
Write-Output 'Top paged pool tags (MB):'
$rows | Sort-Object PagedBytes -Descending | Select-Object -First $Top |
    Select-Object Tag, @{N='MB';E={[math]::Round($_.PagedBytes / 1MB, 2)}}, PagedOutstanding |
    Format-Table -AutoSize | Out-String | Write-Output
Write-Output 'Top nonpaged pool tags (MB):'
$rows | Sort-Object NonpagedBytes -Descending | Select-Object -First $Top |
    Select-Object Tag, @{N='MB';E={[math]::Round($_.NonpagedBytes / 1MB, 2)}}, NonpagedOutstanding |
    Format-Table -AutoSize | Out-String | Write-Output
