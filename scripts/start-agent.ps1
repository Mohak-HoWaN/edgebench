# Start the EdgeBench agent on this PC. It connects to the server, waits for benchmark jobs and runs each in its own process.
#   First time:  .\scripts\start-agent.ps1 -Token <one-time token from the Devices page>
#   Afterwards:  .\scripts\start-agent.ps1            (it remembers who it is; Ctrl+C stops it)
# It uses the heavy runtime environment (.venv-converter or spikes\.venv: ONNX Runtime, OpenVINO, ncnn, PyTorch) when there is one,
# otherwise .venv-agent, in which runs for the missing runtimes are reported as "not available".
param(
    [string]$Server = "http://127.0.0.1:8000",
    [string]$Token = "",
    [string]$Name = ""
)

$root = Split-Path -Parent $PSScriptRoot
$python = @(".venv-converter", "spikes\.venv", ".venv-agent") |
    ForEach-Object { Join-Path $root "$_\Scripts\python.exe" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { throw "No Python environment for the agent was found. See agent\README.md." }

$arguments = @("-m", "edgebench_agent", "--server", $Server)
if ($Token) { $arguments += @("--token", $Token) }
if ($Name) { $arguments += @("--name", $Name) }
Write-Host "agent python: $python"
Push-Location (Join-Path $root "agent")
try { $env:YOLO_AUTOINSTALL = "False"; & $python @arguments } finally { Pop-Location }
