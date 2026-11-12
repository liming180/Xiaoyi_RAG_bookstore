# ============================================================================
#  停止小忆 RAG 后端（Python AI 8000 + Java 8080）
#  双击 deploy\stop-backend.bat 调起本脚本
# ============================================================================

param([switch]$Quiet)

$ErrorActionPreference = 'Continue'
$Ports = @(8000, 8080)

if (-not $Quiet) {
    Write-Host ''
    Write-Host '正在停止后端服务...' -ForegroundColor Yellow
}

$killed = 0

# 1) 先杀 launcher 的 cmd，再杀服务进程。
#    顺序很重要：如果先杀 uvicorn/java，活着的 cmd 可能又去重拉一个，
#    造成「刚停完端口又被占上」。所以先把 cmd 这层拿掉，再清理进程。
$patterns = @(
    'deploy\\run\\java\.cmd',
    'deploy\\run\\ai\.cmd',
    '_dev_up_ai\.py',
    '_dev_up_java\.py'
)
foreach ($pat in $patterns) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pat } |
        ForEach-Object {
            if (-not $Quiet) { Write-Host "  停止 launcher PID $($_.ProcessId)" }
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
}
Start-Sleep -Milliseconds 800

# 2) 按端口杀实际服务
foreach ($port in $Ports) {
    foreach ($procId in (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess) {
        if ($procId) {
            if (-not $Quiet) { Write-Host "  停止端口 $port 的 PID $procId" }
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $killed++
        }
    }
}

# 3) 兜底：按命令行再扫一遍（端口已释放但进程可能还挂着）
foreach ($pat in @('xiaoyi-rag-server', 'uvicorn app\.main:app')) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pat } |
        ForEach-Object {
            if (-not $Quiet) { Write-Host "  补杀 PID $($_.ProcessId)" }
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
}

Start-Sleep -Seconds 1
if (-not $Quiet) {
    Write-Host ''
    if ($killed -eq 0) {
        Write-Host '没有发现正在运行的后端进程。' -ForegroundColor Green
    } else {
        Write-Host "已停止 $killed 个进程。" -ForegroundColor Green
    }
    Write-Host ''
}
