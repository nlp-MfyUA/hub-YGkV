$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    docker build --tag sentiment-agents:hw2 .
    if ($LASTEXITCODE -ne 0) { throw 'Docker 镜像构建失败，请检查 Docker Desktop 是否运行及构建日志。' }
    docker image inspect sentiment-agents:hw2 --format '{{.Id}}'
    if ($LASTEXITCODE -ne 0) { throw '镜像检查失败' }
} finally {
    Pop-Location
}
