# ============================================================================
#  小忆 RAG 后端一键启动（Python AI 8000 + Java 8080）
#
#  一般不用直接跑这个文件，双击同目录的 start-backend.bat 即可。
#
#  关键设计：用 WMI (Win32_Process.Create) 拉起进程，而不是 Start-Process。
#  原因：用 subprocess/Start-Process 起的子进程会被归入调用者的 Windows 作业对象
#  (job object)；IDE 终端、CI、agent 沙箱等在结束时会连带杀掉整棵进程树，
#  表现为「关掉启动窗口后 Java 就没了」。WMI 创建的是独立进程，父进程退出不受影响。
# ============================================================================

[CmdletBinding()]
param(
    [int]$AiPort = 8000,
    [int]$JavaPort = 8080,
    [int]$JavaReadyTimeoutSec = 180,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$RunDir = Join-Path $Root 'deploy\run'
Set-Location $Root

function Write-Head($t) {
    if ($Quiet) { return }
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
}
function Say($msg, $color = 'Gray') { if (-not $Quiet) { Write-Host $msg -ForegroundColor $color } }

function Test-Port([int]$p) {
    [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
}

function Stop-Port([int]$p) {
    foreach ($procId in (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue).OwningProcess) {
        if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
    }
}

# ---------------------------------------------------------------------------
# 启动一个完全独立、且不创建任何窗口的进程
#
# 为什么不用 WMI Create 直接跑 cmd：
#   Win32_Process.Create 执行 `cmd /c xxx.cmd` 时，Windows 会给它配一个真实控制台窗口。
#   那个窗口就是服务的宿主 —— 用户会看到两个空白 cmd 窗口，一旦关掉，
#   里面的 uvicorn / java 立刻收到 ^C 退出，前端登录就变成 502。
#
# 改用 wscript.exe 跑 VBS：
#   wscript 是 GUI 子系统程序，自己不创建控制台；VBS 里用
#   WScript.Shell.Run(..., 0, False) 以「隐藏窗口」样式拉起 cmd，
#   整条进程链都在无窗口状态运行，用户看不到任何窗口，也没有可误关的东西。
#   同时它仍然是独立进程，不挂在调用者的作业对象下，关掉启动窗口也不会停服。
# ---------------------------------------------------------------------------
function Start-HiddenProcess {
    param(
        [Parameter(Mandatory)][string]$VbsPath,
        [string]$Label = 'process'
    )

    if (-not (Test-Path $VbsPath)) {
        throw "缺少隐藏启动器：$VbsPath"
    }

    # wscript 自身瞬间返回，真正的进程（cmd -> uvicorn/java）在后台无窗口运行
    Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$VbsPath`"" -WindowStyle Hidden

    Write-Host "  $Label 已拉起（无窗口）" -ForegroundColor DarkGray
}

function Stop-ByCommandLine($pattern) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

Write-Head '小忆 RAG 后端启动器'

# --- 0. 定位 Python ----------------------------------------------------------
$Python = $env:PYTHON
if (-not $Python -or -not (Test-Path $Python)) {
    foreach ($cand in @('D:\python\python.exe')) {
        if (Test-Path $cand) { $Python = $cand; break }
    }
}
if (-not $Python -or -not (Test-Path $Python)) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { $Python = $found.Source }
}
if (-not $Python -or -not (Test-Path $Python)) {
    Write-Host '[错误] 找不到 python.exe，请设置环境变量 PYTHON 指向它。' -ForegroundColor Red
    return 1
}
Say "  Python: $Python" DarkGray

$Jar = Join-Path $Root 'services\java-api\target\xiaoyi-rag-server-0.1.0-SNAPSHOT.jar'
if (-not (Test-Path $Jar)) {
    Write-Host '[错误] 找不到后端 jar，请先构建：' -ForegroundColor Red
    Write-Host '       cd services/java-api && mvn -DskipTests package' -ForegroundColor Yellow
    return 1
}

# --- 1. 依赖服务 -------------------------------------------------------------
Say ''
Say '[1/5] 检查依赖服务...' Yellow

if (-not (Test-Port 3306)) {
    Say '  MySQL 3306 未监听，尝试启动 MySQL80 服务...' Yellow
    try { Start-Service MySQL80 -ErrorAction Stop } catch { }
    for ($i = 0; $i -lt 10 -and -not (Test-Port 3306); $i++) { Start-Sleep -Seconds 1 }
}
if (Test-Port 3306) { Say '  MySQL   3306  OK' Green }
else {
    Write-Host '  [错误] MySQL 未就绪，后端 Flyway 无法建表。' -ForegroundColor Red
    return 1
}

if (Test-Port 19530) { Say '  Milvus  19530 OK' Green }
else {
    Say '  [警告] Milvus 19530 未监听，向量检索会失败。' Yellow
    Say '         启动：docker start xi-milvus xi-etcd xi-minio' DarkGray
}

# --- 2. 清理旧进程 -----------------------------------------------------------
Say ''
Say '[2/5] 清理上一轮残留进程...' Yellow
$hadOld = $false
foreach ($p in @($AiPort, $JavaPort)) {
    if (Test-Port $p) { Stop-Port $p; $hadOld = $true }
}
# 连 launcher 的 cmd 一起清掉，避免旧 cmd 残留占日志
Stop-ByCommandLine 'deploy\\run\\(java|ai)\.cmd'
Stop-ByCommandLine '_dev_up_ai\.py|_dev_up_java\.py'
if ($hadOld) { Start-Sleep -Seconds 3 } else { Say '  无残留' DarkGray }

# --- 3. 生成启动器 -----------------------------------------------------------
Say ''
Say '[3/5] 生成后端启动器（固化环境变量）...' Yellow
$mk = Join-Path $ScriptDir 'make_launchers.py'
& $Python $mk 2>&1 | ForEach-Object { Say "  $_" DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Host '  [错误] 生成启动器失败。' -ForegroundColor Red
    return 1
}
$aiCmd = Join-Path $RunDir 'ai.cmd'
$javaCmd = Join-Path $RunDir 'java.cmd'
if (-not (Test-Path $aiCmd) -or -not (Test-Path $javaCmd)) {
    Write-Host '  [错误] 启动器缺失。' -ForegroundColor Red
    return 1
}

# --- 4. Python AI ------------------------------------------------------------
Say ''
Say "[4/5] 启动 Python AI（端口 $AiPort）..." Yellow
Start-HiddenProcess -VbsPath (Join-Path $RunDir 'ai-hidden.vbs') -Label 'AI'

Say '  等待 AI 就绪...' DarkGray
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline -and -not (Test-Port $AiPort)) { Start-Sleep -Seconds 2 }
if (-not (Test-Port $AiPort)) {
    Write-Host "  [错误] AI 未在 120 秒内监听 $AiPort，看日志：" -ForegroundColor Red
    Write-Host "         $Root\test-artifacts\dev-ai.log" -ForegroundColor Yellow
    return 1
}
Say "  AI      $AiPort  OK" Green

# --- 5. Java -----------------------------------------------------------------
Say ''
Say "[5/5] 启动 Java 后端（端口 $JavaPort）..." Yellow
Start-HiddenProcess -VbsPath (Join-Path $RunDir 'java-hidden.vbs') -Label 'Java'

Say '  等待 Java 就绪（首次要跑 Flyway，约 50 秒）...' DarkGray
Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(5)
$url = "http://127.0.0.1:$JavaPort/actuator/health"
$deadline = (Get-Date).AddSeconds($JavaReadyTimeoutSec)
$ok = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = $http.GetAsync($url).GetAwaiter().GetResult()
        if ($resp.IsSuccessStatusCode) {
            $body = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if ($body -match '"UP"') { $ok = $true; break }
        }
    } catch { }
    Start-Sleep -Seconds 3
}
if (-not $ok) {
    Write-Host "  [错误] Java 未在 $JavaReadyTimeoutSec 秒内就绪，看日志：" -ForegroundColor Red
    Write-Host "         $Root\test-artifacts\p7-java-fg.log" -ForegroundColor Yellow
    return 1
}
Say "  Java    $JavaPort  OK" Green

# --- 完成 --------------------------------------------------------------------
Say ''
Write-Host '[完成] 全部就绪' -ForegroundColor Green
if (-not $Quiet) {
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
    Write-Host '  后端已启动（独立进程，关掉本窗口不会停）：' -ForegroundColor Cyan
    Write-Host "    Java 后端    http://127.0.0.1:$JavaPort" -ForegroundColor White
    Write-Host "    Python AI    http://127.0.0.1:$AiPort" -ForegroundColor White
    Write-Host ''
    Write-Host '  前端网页      http://127.0.0.1:8088' -ForegroundColor Green
    Write-Host '  账号          admin / Admin@123456' -ForegroundColor White
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
    Write-Host ''
    Write-Host '  停止服务：双击 deploy\stop-backend.bat' -ForegroundColor DarkGray
    Write-Host ''
}

return 0
