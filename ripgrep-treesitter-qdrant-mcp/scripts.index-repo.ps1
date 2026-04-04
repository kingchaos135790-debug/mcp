param(
  [string]$RepoRoot = ".",
  [string]$QdrantUrl = "http://127.0.0.1:16333",
  [string]$Collection = "code_chunks",
  [string]$IndexRoot = "..\data\index"
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot

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

$env:QDRANT_URL = $QdrantUrl
$env:QDRANT_COLLECTION = $Collection
$env:INDEX_ROOT = $resolvedIndexRoot
$env:REPO_ROOT = $resolvedRepoRoot

Push-Location $projectRoot
try {
  npm run index -- "$resolvedRepoRoot"
}
finally {
  Pop-Location
}
