# Install the pinned GitNexus and project-local Node runtime, then build the engine.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
  npm install
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  npm run build
  $setupExitCode = $LASTEXITCODE
}
finally {
  Pop-Location
}
exit $setupExitCode
