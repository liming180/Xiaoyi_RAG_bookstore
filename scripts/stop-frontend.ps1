# ============================================================================
#  停止小忆 RAG 前端 nginx
#  双击 deploy\stop-frontend.bat 调起本脚本
# ============================================================================

$Ngx = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'nginx-windows\nginx-1.27.4'
$Port = 8088

Write-Host ''
Write-Host '正在停止 nginx...' -ForegroundColor Yellow

# 优先优雅退出（会清理 pid 文件）
$pidFile = Join-Path $Ngx 'logs\nginx.pid'
if (Test-Path $pidFile) {
    Push-Location $Ngx
    try { & (Join-Path $Ngx 'nginx.exe') -s stop 2>$null } catch { }
    Pop-Location
    Start-Sleep -Seconds 2
}

# 兜底：按端口杀
$killed = 0
foreach ($procId in (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).OwningProcess) {
    if ($procId) {
        Write-Host "  停止 PID $procId"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}

Start-Sleep -Seconds 1
if ($killed -eq 0) {
    Write-Host 'nginx 已停止（或本来就没在跑）。' -ForegroundColor Green
} else {
    Write-Host "已停止 $killed 个进程。" -ForegroundColor Green
}
Write-Host ''
