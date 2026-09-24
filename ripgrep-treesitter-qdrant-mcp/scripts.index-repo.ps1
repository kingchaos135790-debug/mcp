param(
  [string]$RepoRoot = ".",
  [string]$IndexRoot = "..\data\index"
)

$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot

if ([System.IO.Path]::IsPathRooted($RepoRoot)) {
  $resolvedRepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
} else {
  $resolvedRepoRoot = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $RepoRoot))
}

if ([System.IO.Path]::IsPathRooted($IndexRoot)) {
  $resolvedIndexRoot = [System.IO.Path]::GetFullPath($IndexRoot)
} else {
  $resolvedIndexRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $IndexRoot))
}

$env:INDEX_ROOT = $resolvedIndexRoot
$env:REPO_ROOT = $resolvedRepoRoot

Push-Location $projectRoot
try {
  npm run index -- "$resolvedRepoRoot"
  $indexExitCode = $LASTEXITCODE
}
finally {
  Pop-Location
}

exit $indexExitCode
