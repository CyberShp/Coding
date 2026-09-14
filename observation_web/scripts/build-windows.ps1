param([string]$OutputDirectory = "")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if ($env:OS -ne 'Windows_NT') { throw 'Build on Windows x64 with Python 3.13 and Node.js 22.' }
Push-Location $projectRoot
try {
    python -c "import sys,struct; assert sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8, 'Python 3.13 x64 required'"
    if ($LASTEXITCODE -ne 0) { throw 'Python check failed' }
    $env:CYPRESS_INSTALL_BINARY = '0'
    Push-Location frontend
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
    $arguments = @('scripts/build_windows.py')
    if ($OutputDirectory) { $arguments += @('--output', $OutputDirectory) }
    python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
} finally { Pop-Location }
