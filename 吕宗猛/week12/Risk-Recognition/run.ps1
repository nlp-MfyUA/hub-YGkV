# 一键启动脚本：楼道消防风险识别
# 用法：.\run.ps1                （HTTP 8000 + HTTPS 8443）
#       .\run.ps1 -NoHttps       （只起 HTTP）
param(
    [int]$HttpPort = 8000,
    [int]$HttpsPort = 8443,
    [switch]$NoHttps
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = (Get-Command python -ErrorAction Stop).Source
}

$appScript = Join-Path $here "app.py"
$appArgs = @($appScript, "-HttpPort", $HttpPort, "-HttpsPort", $HttpsPort)
if ($NoHttps) { $appArgs += "-NoHttps" }

& $py @appArgs
