# Compare current-boot kernel pool and process snapshots.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\diagnostics\analyze_pool_growth.ps1
param([int]$Top = 15)

$ErrorActionPreference = 'Stop'
$folder = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\pool-snapshots'
$summaryPath = Join-Path $folder 'pool-summary.csv'
if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "No snapshots found: $summaryPath"
}

$all = @(Import-Csv -LiteralPath $summaryPath)
if ($all.Count -lt 2) { throw 'At least two snapshots are required.' }
$last = $all[-1]
$samples = @($all | Where-Object { $_.BootAt -eq $last.BootAt })
$first = $samples[0]
$start = [datetimeoffset]::Parse($first.RecordedAt)
$end = [datetimeoffset]::Parse($last.RecordedAt)
$hours = ($end - $start).TotalHours
if ($hours -le 0) { throw 'Snapshots have identical timestamps.' }

function Get-TagFile([string]$timestamp) {
    $stamp = ([datetimeoffset]::Parse($timestamp)).ToString('yyyyMMdd-HHmmss-fff')
    return Join-Path $folder ("pool-tags-$stamp.csv")
}

function Get-ProcessFile([string]$timestamp) {
    $stamp = ([datetimeoffset]::Parse($timestamp)).ToString('yyyyMMdd-HHmmss-fff')
    return Join-Path $folder ("processes-$stamp.csv")
}

$initialTagFile = Get-TagFile $first.RecordedAt
$lastTagFile = Get-TagFile $last.RecordedAt
if (-not (Test-Path $initialTagFile) -or -not (Test-Path $lastTagFile)) {
    throw 'Cannot locate the first and last detailed tag snapshots.'
}

# Windows pool tags are case-sensitive. Do not use a PowerShell hashtable
# with default case-insensitive keys to compare tags.
$baselineTags = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal)
foreach ($tag in Import-Csv -LiteralPath $initialTagFile) {
    $baselineTags[$tag.Tag] = $tag
}
$tagDiff = @(
    foreach ($row in Import-Csv -LiteralPath $lastTagFile) {
        if (-not $baselineTags.ContainsKey($row.Tag)) { continue }
        $old = $baselineTags[$row.Tag]
        [pscustomobject]@{
            Tag = $row.Tag
            PagedBeforeMB = [math]::Round(([double]$old.PagedBytes)/1MB, 2)
            PagedNowMB = [math]::Round(([double]$row.PagedBytes)/1MB, 2)
            PagedGrowthMB = [math]::Round((([double]$row.PagedBytes)-([double]$old.PagedBytes))/1MB, 2)
            NonpagedGrowthMB = [math]::Round((([double]$row.NonpagedBytes)-([double]$old.NonpagedBytes))/1MB, 2)
            PagedOutstandingDelta = ([long]$row.PagedOutstanding - [long]$old.PagedOutstanding)
        }
    }
)

Write-Output ("Snapshots: {0} (same boot)" -f $samples.Count)
Write-Output ("Period: {0} -> {1} ({2:N2} h)" -f $start.ToString('yyyy-MM-dd HH:mm:ss'), $end.ToString('yyyy-MM-dd HH:mm:ss'), $hours)
foreach ($field in @('CommittedMB', 'PagedPoolMB', 'NonpagedPoolMB')) {
    $delta = [double]$last.$field - [double]$first.$field
    Write-Output ("{0}: {1:N1} -> {2:N1} MB; change {3:+0.0;-0.0;0} MB ({4:+0.0;-0.0;0} MB/h)" -f $field, [double]$first.$field, [double]$last.$field, $delta, ($delta/$hours))
}
if ($hours -lt 1) {
    Write-Output 'Observation period is short. Do not infer a leak from these deltas alone.'
}
Write-Output 'Top paged pool growth:'
$tagDiff | Sort-Object PagedGrowthMB -Descending | Select-Object -First $Top |
    Format-Table -AutoSize | Out-String | Write-Output
Write-Output 'Top nonpaged pool growth:'
$tagDiff | Sort-Object NonpagedGrowthMB -Descending | Select-Object -First $Top |
    Format-Table -AutoSize | Out-String | Write-Output

$firstProc = Get-ProcessFile $first.RecordedAt
$lastProc = Get-ProcessFile $last.RecordedAt
if ((Test-Path $firstProc) -and (Test-Path $lastProc)) {
    # Only compare the same process ID; a replacement process is not a leak.
    $oldProcesses = @{}
    foreach ($row in Import-Csv $firstProc) {
        $oldProcesses[$row.Id] = $row
    }
    $processChanges = @(
        foreach ($row in Import-Csv $lastProc) {
            if (-not $oldProcesses.ContainsKey($row.Id)) { continue }
            $old = $oldProcesses[$row.Id]
            if ($old.ProcessName -ne $row.ProcessName) { continue }
            [pscustomobject]@{
                Name = $row.ProcessName
                PID = $row.Id
                PrivateGrowthMB = [math]::Round((([double]$row.PrivateMemorySize64)-([double]$old.PrivateMemorySize64))/1MB, 2)
                PrivateNowMB = [math]::Round(([double]$row.PrivateMemorySize64)/1MB, 2)
            }
        }
    )
    Write-Output 'Top private memory growth for surviving PIDs:'
    $processChanges | Sort-Object PrivateGrowthMB -Descending | Select-Object -First $Top |
        Format-Table -AutoSize | Out-String | Write-Output
}
