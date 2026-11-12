# 一键启动说明（Windows 本机）

本目录下四个 `.bat` 都是双击即用。不需要开命令行、不需要记命令。

| 文件 | 作用 |
|---|---|
| `start-frontend.bat` | 启动 nginx（前端页面 + API 反代），并自动打开浏览器 |
| `start-backend.bat` | 启动 Python AI（8000）和 Java 后端（8080），等两个都健康才返回 |
| `stop-frontend.bat` | 停止 nginx |
| `stop-backend.bat` | 停止 Python AI 和 Java 后端 |

## 正常使用顺序

```
1. 双击 start-backend.bat     ← 等它显示「[5/5] 全部就绪」
2. 双击 start-frontend.bat    ← 浏览器会自动打开
3. 在浏览器里输入/确认地址：http://127.0.0.1:8088
4. 登录：admin / Admin@123456
```

关闭时顺序相反：先 `stop-frontend.bat`，再 `stop-backend.bat`。

**启动窗口可以关掉，服务不会停。** 四个服务都以独立进程拉起，不挂在启动窗口下面。
要停服务请用对应的 `stop-*.bat`，直接关窗口只是关掉那个黑框。

## 关于「关窗口不掉服务」是怎么做到的

这不是随便写个 `start` 就行的，里面有两个坑，都已经处理：

**坑一：作业对象连带杀。** 用 `subprocess.Popen` / `Start-Process` 起的子进程会被归入
调用者的 Windows 作业对象 (job object)。IDE 终端、CI、agent 沙箱这类环境在结束时
会连带杀掉整棵进程树，表现为「关掉窗口后 Java 就没了」。

→ 解法：后端改用 **WMI (`Win32_Process.Create`)** 创建进程。WMI 拉起的是独立进程，
不属于调用者的作业对象，父进程退出完全不影响它。

**坑二：环境变量靠父进程传。** 原来 `_dev_up_java.py` 用 `Popen(env=...)` 传环境变量，
父进程一没，后续重启就丢了配置。

→ 解法：`deploy/scripts/make_launchers.py` 先把配置**固化成字面量**写进
`deploy/run/java.cmd` 和 `ai.cmd`，再让 WMI 执行这两个 `.cmd`。启动器自包含，
不依赖任何外部环境。

前端 nginx 同理：`nginx.exe` 在 Windows 上会驻留前台并继承父句柄，
必须用独立方式拉起（`Start-Process` 且**不能**加 `-WindowStyle Hidden`，
否则 nginx 会套在隐藏窗口站里无法初始化）。

> 生成出来的 `deploy/run/*.cmd` 含明文密码与 API key，已加入 `.gitignore`，
> 不进版本库。每次启动后端会自动重新生成，不需要手工维护。

---

## 端口占用

| 端口 | 服务 | 说明 |
|---|---|---|
| 8088 | nginx | **这是你要在浏览器打开的地址** |
| 8080 | Java 后端 | API 服务，浏览器直连会看到 JSON，不是网页 |
| 8000 | Python AI | 内部服务，仅 Java 调用 |
| 3306 | MySQL | 数据库 |
| 19530 | Milvus | 向量库 |

> 直接访问 8000 或 8080 看到 `{"detail":"Not Found"}` 或 `{"code":50000,...}` 是正常现象，
> 它们是给程序调用的接口服务，没有网页。网页入口永远是 **8088**。

## 依赖服务的启动

`start-backend.bat` 会检查 MySQL 和 Milvus：

- **MySQL（3306）**：没跑时会自动 `net start MySQL80`
- **Milvus（19530）**：没跑时只告警，不阻塞。需要时手动执行：
  ```
  docker start xi-milvus xi-etcd xi-minio
  ```

## 前端产物更新

改了前端代码后，需要重新构建并复制到 nginx 目录：

```powershell
cd frontend
npm run build:only
xcopy /E /I /Y dist "..\deploy\nginx-windows\nginx-1.27.4\html"
```

然后重跑 `start-frontend.bat`。

## 排错

### 弹出了两个空白 cmd 窗口，关掉它们之后登录就 502

**现象**：双击 `start-backend.bat` 后，屏幕上多出两个空白黑色 cmd 窗口，
里面没有任何内容。把这两个窗口关掉，前端就登录不了（接口返回 502）。

**根因**：早期版本用 `WMI (Win32_Process.Create)` 执行 `cmd /c ai.cmd`。
Windows 会给这个 cmd 配一个**真实控制台窗口**，而 uvicorn / java 就运行在那个窗口里。
所以那两个「空白窗口」其实是服务的宿主 —— 关掉它们，服务立刻收到 `^C` 退出。
日志末尾能看到痕迹：

```
INFO:  Uvicorn running on http://127.0.0.1:8000
^C                        ← 关窗口时发来的中断
```

**已修复**：改用 `wscript.exe` + VBS 以**隐藏窗口**方式启动。

- `wscript` 是 GUI 子系统程序，自己不创建控制台
- VBS 里 `WScript.Shell.Run(..., 0, False)` 的第二个参数 `0` 表示隐藏窗口
- 整条进程链（wscript → cmd → uvicorn/java）都在无窗口状态下运行
- 仍是独立进程，不挂在启动窗口的作业对象下，关掉启动窗口也不停服

启动时你会看到 `AI 已拉起（无窗口）`，这是正常的，**不再有任何窗口需要你保管**。

验证方法（应输出 0）：

```powershell
(Get-Process cmd -ErrorAction SilentlyContinue |
  Where-Object { $_.MainWindowHandle -ne 0 } | Measure-Object).Count
```

### 卡在「等待 AI 就绪」然后退出

**现象**：`start-backend.bat` 走到 `[4/5] 启动 Python AI` 后一直「等待 AI 就绪」，
最后报「AI 未在 120 秒内监听 8000」，而 `test-artifacts\dev-ai.log` 里只有一行
`[launcher] started ...`，没有任何 Python 输出。

**根因**：`deploy/run/*.cmd` 是**批处理文件**，cmd.exe 按系统 ANSI 代码页（中文 Windows 是
GBK/936）解析它。如果文件是 UTF-8 且含中文（注释或环境变量值里的中文路径），
cmd 会把 UTF-8 字节按 GBK 解码成乱码，乱码里的残留字符被当成命令执行，
整个启动器在执行第一行实质命令前就崩了 —— 所以日志只有 started、进程立刻退出、端口不监听。

**已修复**（`deploy/scripts/make_launchers.py`）：

1. `.cmd` 内注释一律用**英文**，不用中文
2. 只固化白名单里的必要变量（`KEEP_ENV_KEYS`），不再整体复制 `os.environ`
   —— 避免把带中文路径的宿主变量（如 `D:\网站UI设计\...`）写进文件
3. 写盘前**强校验 ASCII**，一旦有非 ASCII 直接报错退出，不会生成坏的启动器

验证方法：

```powershell
# 两个文件都应能纯 ASCII 解码
python -c "print(open(r'deploy/run/ai.cmd','rb').read().decode('ascii')[:80])"
```

如果再次出现这个现象，先看这条：

```powershell
# 手动跑一次启动器，直接看报错（powerShell 里执行，不要双击）
& 'D:\VM1\Xiaoyi_RAG_bookstore\deploy\run\ai.cmd'
```

正常应该看到 `Uvicorn running on http://127.0.0.1:8000`。

### 登录不上去 / 接口 502

前端能打开但登录失败，基本都是**后端没在跑**。按顺序查：

1. 看端口：`Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8000,8080 }`
2. 少了就双击 `start-backend.bat`，**等它显示「[完成] 全部就绪」再做别的**
3. 后端首次启动要跑 Flyway，约 50 秒，别急着关窗口

两个内置账号：

| 账号 | 密码 | 角色 | 登录后进入 |
|---|---|---|---|
| `admin` | `Admin@123456` | 管理员 | 管理端 `/admin/users` |
| `user` | `User@12345678` | 普通用户 | 对话 `/chat` |

### 其他排错

| 现象 | 原因与处理 |
|---|---|
| 页面能开，登录失败 | 后端没起。跑 `start-backend.bat`，或检查 8080 是否监听 |
| 提示找不到 jar | 先构建：`cd server-java && mvn -DskipTests package` |
| 提示缺少 html\index.html | 前端产物没复制，见上面「前端产物更新」 |
| nginx 起不来 | 看 `nginx-windows\nginx-1.27.4\logs\error.log` |
| 后端起不来 | 看 `..\test-artifacts\p7-java-fg.log` 和 `dev-ai.log` |
| 端口被占用 | 先跑对应的 `stop-*.bat`，脚本也会自动停旧实例 |

## 目录结构

```
deploy/
  start-backend.bat          ← 双击
  start-frontend.bat         ← 双击
  stop-backend.bat
  stop-frontend.bat
  scripts/
    start-backend.ps1        ← 实际逻辑（WMI 起进程）
    start-frontend.ps1
    stop-backend.ps1
    stop-frontend.ps1
    make_launchers.py        ← 生成下面 run/ 里的启动器
  run/                       ← 自动生成，含密钥，已 gitignore
    java.cmd
    ai.cmd
  nginx-windows/
    nginx-1.27.4/
      nginx.exe
      conf/nginx.conf        ← 监听 8088，/api 反代到 8080
      html/                  ← 前端 build 产物
```
