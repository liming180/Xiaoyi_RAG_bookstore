# ============================================================================
#  小忆 RAG 前端启动（nginx 静态托管 + API 反代）
#
#  一般不用直接跑，双击同目录的 start-frontend.bat 即可。
# ============================================================================

[CmdletBinding()]
param(
    [int]$Port = 8088,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # deploy\scripts
$Root      = Split-Path -Parent $ScriptDir   # 项目根
$Ngx = Join-Path $Root 'infra\nginx\nginx-1.27.4'
$Exe = Join-Path $Ngx 'nginx.exe'
$Url = "http://127.0.0.1:$Port"

function Write-Head($t) {
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
}

function Test-Port([int]$p) {
    [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
}

Write-Head '小忆 RAG 前端（nginx）启动器'

# --- 1. 自检 -----------------------------------------------------------------
if (-not (Test-Path $Exe)) {
    Write-Host "[错误] 找不到 nginx.exe：$Exe" -ForegroundColor Red
    return 1
}
$indexHtml = Join-Path $Ngx 'html\index.html'
if (-not (Test-Path $indexHtml)) {
    Write-Host '[错误] 缺少前端产物 html\index.html' -ForegroundColor Red
    Write-Host '       构建并复制：' -ForegroundColor Yellow
    Write-Host '         cd frontend && npm run build:only' -ForegroundColor Yellow
    Write-Host "         xcopy /E /I /Y apps\web\dist `"$Ngx\html`"" -ForegroundColor Yellow
    return 1
}

# --- 2. 清理旧实例 -----------------------------------------------------------
if (Test-Port $Port) {
    Write-Host "[提示] $Port 被占用，停止旧实例..." -ForegroundColor Yellow
    foreach ($procId in (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).OwningProcess) {
        if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Seconds 2
}

# --- 3. 配置检查 -------------------------------------------------------------
Write-Host '[1/3] 检查 nginx 配置...' -ForegroundColor Yellow
Push-Location $Ngx
try {
    # nginx -t 把正常信息也写到 stderr，PowerShell 会当成 NativeCommandError，
    # 所以临时放宽 ErrorActionPreference，只用退出码判断成败。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = & $Exe -t 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($code -ne 0) {
        Write-Host '  [错误] 配置有误：' -ForegroundColor Red
        $out | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        return 1
    }
    Write-Host '  配置 OK' -ForegroundColor Green
}
finally { Pop-Location }

# --- 4. 启动 -----------------------------------------------------------------
Write-Host '[2/3] 启动 nginx...' -ForegroundColor Yellow
# 用 VBS 的 WScript.Shell.Run(...,0,False) 启动，才能真正脱离父进程：
# 在 Windows 上 nginx.exe 会驻留前台并继承父进程句柄，用 Start-Process 或直接调用
# 都会让 nginx 随启动它的 shell 结束而退出（表现为「关掉 bat 窗口网页就打不开」）。
# 用 Start-Process 起 nginx。实测要点：
#   - 不能加 -WindowStyle Hidden：会给进程套一个隐藏的窗口站，
#     nginx 在这种环境下常无法完成初始化（error.log 一片空白，端口也不监听）。
#   - 不要 -Wait：nginx 常驻，-Wait 会永久阻塞。
#   - 必须给 -WorkingDirectory，否则 nginx 找不到相对的 conf/logs 路径。
Start-Process -FilePath $Exe -WorkingDirectory $Ngx

$deadline = (Get-Date).AddSeconds(30)
$up = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Port $Port) { $up = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $up) {
    Write-Host "  [错误] nginx 未监听 $Port，日志：" -ForegroundColor Red
    Write-Host "         $(Join-Path $Ngx 'logs\error.log')" -ForegroundColor Yellow
    return 1
}
Write-Host "  nginx $Port OK" -ForegroundColor Green

# --- 5. 后端检查 -------------------------------------------------------------
Write-Host '[3/3] 检查后端...' -ForegroundColor Yellow
$backendOk = $false
try {
    $r = Invoke-WebRequest -Uri "$Url/healthz" -UseBasicParsing -TimeoutSec 4
    if ($r.StatusCode -eq 200) { $backendOk = $true }
} catch { }
if ($backendOk) {
    Write-Host '  后端 OK' -ForegroundColor Green
} else {
    Write-Host '  [警告] 后端未就绪：页面能打开，但登录会失败。' -ForegroundColor Yellow
    Write-Host '         请先运行 deploy\start-backend.bat' -ForegroundColor Yellow
}

Write-Host ''
Write-Host ('=' * 60) -ForegroundColor DarkCyan
Write-Host '  前端已启动' -ForegroundColor Green
Write-Host ''
Write-Host "    打开浏览器：  $Url" -ForegroundColor White
Write-Host ''
Write-Host '  停止服务：双击 deploy\stop-frontend.bat' -ForegroundColor DarkGray
Write-Host ('=' * 60) -ForegroundColor DarkCyan

if (-not $NoBrowser) { Start-Process $Url }

return 0
