# Start EdgeBench locally: the API, the built web app, and the converter if one is set up.
#   .\scripts\start-server.ps1            then open http://127.0.0.1:8000     (Ctrl+C stops it)
#   .\scripts\start-server.ps1 -Port 8001
# Data (database, uploaded models, converted files) lives in .\data and survives restarts.
param([int]$Port = 8000)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "The server environment is missing. Create it first (README, 'Run it')." }

# The converter environment: the one from converter\README.md, or the Phase 0 spike environment (same package versions).
$converter = @(".venv-converter", "spikes\.venv") |
    ForEach-Object { Join-Path $root "$_\Scripts\python.exe" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1

$env:EDGEBENCH_WEB_DIST = Join-Path $root "web\dist"
$env:EDGEBENCH_DATA_DIR = Join-Path $root "data"
$env:EDGEBENCH_PORT = "$Port"
if ($converter) { $env:EDGEBENCH_CONVERTER_PYTHON = $converter }

if (-not (Test-Path (Join-Path $env:EDGEBENCH_WEB_DIST "index.html"))) {
    Write-Warning "web\dist is missing, so there is no web app to show. Run:  cd web; npm run build"
}
Write-Host "EdgeBench on http://127.0.0.1:$Port"
Write-Host ("converter: " + $(if ($converter) { $converter } else { "none (models can be uploaded but not read or converted)" }))
& $python -m edgebench
