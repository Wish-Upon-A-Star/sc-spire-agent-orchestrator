$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$server = Join-Path $repoRoot "tools\sc_spire_agent_sdk_orchestrator\viewer_server.py"
$port = 8766

$python = $venvPython
$pythonArgsPrefix = @()
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
  & $pyLauncher.Source -3.13 -c "import agents" *> $null
  if ($LASTEXITCODE -eq 0) {
    $python = $pyLauncher.Source
    $pythonArgsPrefix = @("-3.13")
  }
}

if (-not (Test-Path -LiteralPath $python)) {
  throw "Python runtime not found: $python"
}

$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
  $pidToStop = $conn.OwningProcess
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidToStop"
  if ($proc.CommandLine -like "*viewer_server.py*") {
    Stop-Process -Id $pidToStop
    Start-Sleep -Milliseconds 500
  }
}

$serverArgs = @() + $pythonArgsPrefix + @("-B", $server, "--host", "127.0.0.1", "--port", "$port")
Start-Process -FilePath $python -ArgumentList $serverArgs -WorkingDirectory $repoRoot -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:$port"
