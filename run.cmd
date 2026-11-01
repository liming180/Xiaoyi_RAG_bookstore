@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 py 启动器，请先安装 Python 3.10 及以上版本。
    pause
    exit /b 1
)

echo ============================================================
echo  星河读书会 . 个人资料助手
echo ============================================================
echo  正在启动本地服务，请用浏览器打开 http://127.0.0.1:8765
echo  关闭本窗口即可停止服务。
echo ============================================================
echo.

if not exist "frontend\dist\index.html" (
    echo [提示] 没有找到前端构建产物 frontend\dist\index.html。
    echo        页面会显示"前端产物缺失"，但 /api 接口仍可正常使用。
    echo        要恢复界面，请先构建一次前端：
    echo            cd frontend
    echo            npm install
    echo            npm run build
    echo.
)

py -3.12 -X utf8 -m app.api
if errorlevel 1 (
    echo.
    echo [提示] 启动失败，请把上面的完整报错发给老师或 AI 助手分析原因。
    pause
)
endlocal
