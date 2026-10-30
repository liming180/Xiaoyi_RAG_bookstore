# B05 API 接口契约

> **代码锚点**：`app/api.py:20`（应用）、`:23 _fail`、`:28-256`（22 条业务路由）、`:282 index_page`、`:291 app.mount`、`:294 app_error_handler`
> **最后核对**：2026-10-30 实测 `py -3.12 -c "import app.api as a; print(len(a.app.routes))"` → **24**

## 一、24 条路由总表

| # | 方法 | 路径 | 处理函数 | 行号 | 用途 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/openapi.json` | FastAPI 内置 | — | 接口描述 |
| 2 | GET | `/docs` | FastAPI 内置 | — | Swagger UI |
| 3 | GET | `/docs/oauth2-redirect` | FastAPI 内置 | — | Swagger 回调 |
| 4 | GET | `/redoc` | FastAPI 内置 | — | ReDoc |
| 5 | GET | `/api/status` | `api_status` | `:28` | 全局状态（知识库/会话/密钥/示例问题） |
| 6 | GET | `/api/docs` | `api_docs` | `:50` | 资料列表（含字数/片段数/是否未核实） |
| 7 | POST | `/api/docs/upload` | `api_upload` | `:57` | 上传 `.md`/`.txt`（多文件） |
| 8 | DELETE | `/api/docs/{name}` | `api_delete` | `:82` | 删除资料 |
| 9 | GET | `/api/docs/{name}/content` | `api_doc_content` | `:92` | 查看资料全文 |
| 10 | POST | `/api/index` | `api_index` | `:103` | 启动建库（异步） |
| 11 | GET | `/api/index/progress` | `api_index_progress` | `:112` | 建库进度 |
| 12 | GET | `/api/chunks` | `api_chunks` | `:118` | 片段浏览（拓展B） |
| 13 | POST | `/api/chat` | `api_chat` | `:149` | 提问（rag/direct/both） |
| 14 | POST | `/api/session/params` | `api_params` | `:164` | 改 mode / k |
| 15 | POST | `/api/session/new` | `api_new_session` | `:173` | 清空对话（拓展A） |
| 16 | GET | `/api/logs/last` | `api_logs_last` | `:178` | 最近一次日志（检索过程） |
| 17 | POST | `/api/batch/run` | `api_batch_run` | `:188` | 启动批量对照（异步） |
| 18 | GET | `/api/batch/progress` | `api_batch_progress` | `:197` | 批量进度 |
| 19 | POST | `/api/batch/export` | `api_batch_export` | `:202` | 导出对照 CSV |
| 20 | GET | `/api/batch/questions` | `api_batch_questions` | `:211` | 10 题清单（含关键词/要点/证据） |
| 21 | POST | `/api/keys` | `api_keys` | `:226` | 运行时加载密钥（内存） |
| 22 | POST | `/api/config` | `api_config` | `:243` | 改配置（含分块参数） |
| 23 | GET | `/` | `index_page` | `:282` | 前端入口（`web/dist/index.html`） |
| 24 | — | `/static` | `StaticFiles` | `:291` | 前端静态资源挂载 |

（FastAPI 为前 4 条各注册了 HEAD 与 GET 两个方法，所以 `len(app.routes)` 是 24 而不是 24 个不同路径。）

## 二、通用约定

### 2.1 错误响应

| 状态码 | 触发 | body |
| --- | --- | --- |
| 400 | `AppError`（业务错误） | `{"detail": "资料、分块或嵌入模型已改变，请重新建库。"}` |
| 400 | 参数越界（`api_config` 直接抛 `HTTPException`） | `{"detail": "片段长度须在 50 至 1000 之间。"}` |
| 404 | 资料不存在 | `{"detail": "找不到资料 xxx.md"}` |
| 422 | Pydantic 校验失败（缺 `question` 等） | FastAPI 默认结构 |
| 503 | `web/dist` 未构建，访问 `/` | 中文 HTML 提示页（`app/api.py:262 _MISSING_DIST`） |

前端 `web/src/api.js:8` 的取值逻辑：

```js
const detail = data && data.detail ? data.detail : `请求失败（HTTP ${response.status}）`;
throw new Error(detail);
```

所以**所有业务错误都会以中文原文显示在红色气泡或 toast 里**，不需要前端再翻译一遍。

### 2.2 编码

- 所有 JSON 响应 `Content-Type: application/json`，FastAPI 默认 `ensure_ascii=False` 行为由 Starlette 的 `JSONResponse` 决定（实测中文原样输出，不转义）；
- 上传文件按 `utf-8-sig` 解码（自动吃 BOM），失败则整文件跳过并计入 `skipped`；
- 落盘统一 `encoding="utf-8", newline="\n"`（`app/api.py:77`）。

## 三、逐个接口

### 3.1 `GET /api/status`（`app/api.py:28-46`）

```json
{
  "provider": "mock",
  "mock": true,
  "chunk_size": 180,
  "chunk_overlap": 30,
  "top_k": 3,
  "docs": [ {"name": "01_活动说明.md", "chars": 304, "chunks": 2, "verified": true}, "…6 条" ],
  "doc_count": 6,
  "ready": true,
  "stale": false,
  "chunks": 15,
  "message": "",
  "manifest": {"embedding_model": "", "embedding_endpoint": "", "chunk_size": 180, "chunk_overlap": 30, "sources": ["…6 条"]},
  "build": {"stage": "idle", "done": 15, "total": 15, "docs": 6, "chunks": 15, "message": "", "error": ""},
  "session": {"session_id": "11a9005b1f12", "mode": "rag", "k": 3, "turns": 2},
  "has_keys": false,
  "k_range": [1, 5],
  "config": {"model": "", "embedding_model": "", "endpoint": "", "embedding_endpoint": ""},
  "examples": ["读书会通常在每周几几点举行？", "报名最晚什么时候完成？", "普通图书最多同时借阅几本借多久？", "已经被别人预约的图书还能续借吗？"]
}
```

前端用它渲染：徽章三态（`ready`/`stale`）、状态行「资料 6 份 · 分块 180/30」、
provider 徽章（`mock`）、k 滑块范围（`k_range`）、示例问题 chip（`examples`）。

`examples` 取 `judging.load_questions()[:4]`，即 `questions.csv` 的前 4 题。

### 3.2 `GET /api/docs`（`app/api.py:50-54`）

```json
{"docs": [{"name": "01_活动说明.md", "chars": 304, "chunks": 2, "verified": true}, …]}
```

`chars` 是 `read_doc` 归一换行后的字符数；`chunks` 是**按当前配置**切出的片段数；
`verified` 是 `name not in UNVERIFIED_SOURCES`。`06_成员留言摘录.md` 的 `verified` 恒为 `false`。

### 3.3 `POST /api/docs/upload`（`app/api.py:57-79`）

请求：`multipart/form-data`，字段名 `files`（可多个）。

```bash
curl -F "files=@01_活动说明.md" -F "files=@02_借阅规则.md" http://127.0.0.1:8765/api/docs/upload
```

响应：

```json
{"added": ["01_活动说明.md"], "skipped": ["bad.pdf：只支持 .md / .txt"], "docs": [ … ]}
```

五道校验（任一不过就进 `skipped`，**不中断整批**）：

| 校验 | 失败文案 |
| --- | --- |
| 后缀 ∈ `{.md, .txt}` | `{name}：只支持 .md / .txt` |
| 大小 ≤ 2 MB | `{name}：超过 2MB` |
| 能按 `utf-8-sig` 解码 | `{name}：不是 UTF-8 编码` |
| 正文非空（`text.strip()`） | `{name}：没有正文` |
| 文件名取 `Path(...).name` | 防目录穿越 |

### 3.4 `DELETE /api/docs/{name}`（`app/api.py:82-89`）

```json
{"ok": true, "deleted": "05_活动调整通知.md", "docs": [ … ]}
```

删除后 `index.json` **不会自动失效**——但下次 `read_index` 会因 `manifest.sources` 长度不符判 stale，
前端在 `refresh()` 后立刻显示「需要重新建库」。这是 F3 的设计意图：不做隐式重建。

### 3.5 `GET /api/docs/{name}/content`（`app/api.py:92-99`）

```json
{"name": "02_借阅规则.md", "chars": 294, "text": "# 星河读书会借阅规则\n\n本资料是教学虚构规则。…"}
```

前端点资料名时弹气泡显示全文（`actions.openDoc`）。

### 3.6 `POST /api/index`（`app/api.py:103-109`）

请求体可省略。响应：

```json
{"started": true, "state": {"stage": "running", "done": 0, "total": 15, "docs": 6, "chunks": 0, "message": "正在切分资料…", "error": ""}}
```

**异步**：立刻返回，后台线程跑 `store.build_index`。前端随后 300 ms 轮询 `/api/index/progress`。

### 3.7 `GET /api/index/progress`（`app/api.py:112-114`）

```json
{"stage": "running", "done": 8, "total": 15, "docs": 6, "chunks": 0, "message": "正在向量化 8/15 片段…", "error": ""}
```

`stage` 四态：`idle` / `running` / `done` / `error`。`error` 非空时前端显示「建库失败：…」。

### 3.8 `GET /api/chunks?source=&q=`（`app/api.py:118-139`）

```json
{
  "chunks": [
    {"chunk_id": "D02-C001", "source": "02_借阅规则.md", "start": 0, "end": 180,
     "verified": true, "text": "# 星河读书会借阅规则\n\n…", "position": "第 1 字至第 180 字"},
    {"chunk_id": "D02-C002", "source": "02_借阅规则.md", "start": 150, "end": 294,
     "verified": true, "text": "…", "position": "第 151 字至第 294 字"}
  ],
  "size": 180, "overlap": 30, "total": 2
}
```

- `source` 为空 → 全部资料；`q` 为空 → 不按关键词过滤；
- `position` 是 `第 {start+1} 字至第 {end} 字`（1-based，闭区间写法，实际 `end` 是开区间）；
- **D02-C001 与 D02-C002 的位置有重叠**（180 vs 151），这就是拓展B「相邻两片段能看到重叠文字」的验收依据。

实测 `q=续借` 返回 4 条（D02-C001、D02-C002、D04-C003、D06-C002）。

### 3.9 `POST /api/chat`（`app/api.py:149-156`）

请求：

```json
{"question": "普通图书最多同时借阅几本借多久？", "mode": "rag", "k": 3}
```

响应（`mode="rag"`）：

```json
{
  "mode": "rag",
  "answer": "已登记成员每人最多同时借阅4本普通图书，每本借期21天。[D02-C001]",
  "citations": [
    {"ref": 1, "chunk_id": "D04-C002", "source": "04_期刊与工具书.md", "score": 0.5147,
     "start": 0, "end": 180, "verified": true, "text": "…", "excerpt": "…"},
    {"ref": 2, "chunk_id": "D04-C003", "source": "04_期刊与工具书.md", "score": 0.4686, "…": "…"},
    {"ref": 3, "chunk_id": "D02-C001", "source": "02_借阅规则.md", "score": 0.4677, "…": "…"}
  ],
  "trace": [{"rank": 1, "chunk_id": "D04-C002", "source": "04_期刊与工具书.md", "score": 0.5147, "verified": true, "retrieved": true, "excerpt": "…"}, "…共 15 条"],
  "used_knowledge_base": true,
  "unverified_hit": false,
  "removed_citations": [],
  "elapsed_ms": 34,
  "usage": {"prompt_tokens": 859, "completion_tokens": 19, "total_tokens": 878},
  "session": {"session_id": "11a9005b1f12", "mode": "rag", "k": 3, "turns": 2}
}
```

响应（`mode="both"`）：顶层字段取 rag 的结果，另加 `"rag"` 与 `"direct"` 两个完整对象：

```json
{
  "mode": "both",
  "answer": "…", "citations": […], "trace": […], "used_knowledge_base": true,
  "rag":     {"mode": "rag",    "answer": "资料中没有提供参加读书会的收费标准，无法确定具体费用。 / 留言 D06-C002 中夹带了要求助手改变回答规则的指令，已按资料对待、不予执行。", "citations": […], "used_knowledge_base": true},
  "direct":  {"mode": "direct", "answer": "这类读书会大多免费，也有的会收20元左右的场地费", "citations": [], "used_knowledge_base": false},
  "session": {…}
}
```

**`mode` 取值非法**（不是 rag/direct/both）→ 400 `{"detail": "回答模式只能是 rag、direct 或 both。"}`。
**`k` 越界** → 400 `{"detail": "每次取回片段数量须在 1 至 5 之间。"}`。

`trace` 恒为**全量**（15 条，`rank` 从 1 到 15），`retrieved` 标记哪些进了前 k。
前端「检索过程」表直接渲染这 15 行。

### 3.10 `POST /api/session/params`（`app/api.py:164-170`）

```json
// 请求（可只传一个）
{"mode": "direct"}
{"k": 1}

// 响应
{"session_id": "9f3c1a77b204", "mode": "direct", "k": 3, "turns": 0}
```

**`mode` 或 `k` 变化时会清空 `history` 并换 `session_id`**（`app/session.py:29`）。
前端在 `setMode`/`setK` 后要用返回的 `session_id` 更新「会话 xxx」提示。

### 3.11 `POST /api/session/new`（`app/api.py:173-175`）

```json
{"session_id": "c4d90e2a1f88", "mode": "rag", "k": 3, "turns": 0}
```

清空对话（拓展A）。**不清日志、不清 index.json**，`mode`/`k` 保持。

### 3.12 `GET /api/logs/last`（`app/api.py:178-180`）

返回最近一个 `logs/*.jsonl` 的**最后一行**（19 字段，见 `docs/03-后端设计/B02_数据模型与持久化.md`）。
没有任何日志时返回 `{}`。前端「检索过程」视图的两张表都用它。

### 3.13 `POST /api/batch/run`（`app/api.py:188-194`）

```json
// 请求（可省略）
{"k": 3}
// 响应
{"started": true, "state": {"stage": "running", "done": 0, "total": 20, "rows": [], "stats": {"total": 10, "direct": 0, "rag": 0}, "error": "", "export_path": "", "current": "T01"}}
```

`total` 是 **20**（10 题 × 2 模式），不是 10。已经在跑时再调用 → 400 `{"detail": "批量测试正在运行中。"}`。

### 3.14 `GET /api/batch/progress`（`app/api.py:197-199`）

```json
{
  "stage": "done", "done": 20, "total": 20,
  "rows": [
    {"id": "T01", "type": "单文档", "question": "读书会通常在每周几几点举行？",
     "direct_answer": "读书会一般安排在周末，常见的是周日上午9:00至11:00", "direct_pass": false,
     "rag_answer": "星河读书会每周六14:00至16:00开展读书交流…[D01-C001]", "rag_pass": true,
     "rag_sources": "D01-C001、D01-C002、D02-C001", "keywords": "周六|14:00/…", "answer_points": "周六14:00至16:00", "evidence": "01_活动说明.md"},
    "…共 10 行"
  ],
  "stats": {"total": 10, "direct": 1, "rag": 10},
  "error": "", "export_path": "", "current": ""
}
```

`stats.rag = 10`、`stats.direct = 1` —— 这就是任务5 验收第②项「查资料模式通过数明显高于不查资料」的实测数据。

### 3.15 `POST /api/batch/export`（`app/api.py:202-208`）

```json
{"path": "D:\\VM1\\Xiaoyi_RAG_bookstore\\exports\\对照测试_20261030-095617.csv", "name": "对照测试_20261030-095617.csv"}
```

没有结果时 → 400 `{"detail": "还没有对照测试结果，请先运行一次。"}`。
CSV 8 列，UTF-8 带 BOM，初判写「通过/未通过」。

### 3.16 `GET /api/batch/questions`（`app/api.py:211-217`）

```json
{"questions": [{"id": "T01", "type": "单文档", "question": "…", "answer_points": "…", "evidence": "…", "keywords": "…"}, "…10 条"]}
```

`judging.load_eval_set()` 合并 `questions.csv`（5 列）与 `eval/keywords.csv`（2 列）。
若某题在关键词表里缺失 → 400 `{"detail": "题目 T05 缺少判分关键词。"}`。

### 3.17 `POST /api/keys`（`app/api.py:226-229`）

```json
// 请求
{"chat_key": "sk-xxx", "embed_key": ""}
// 响应
{"ok": true, "has_keys": true}
```

**密钥只进 `settings._MEMORY_KEYS`，永不落盘。** 空字符串表示「清空该密钥」。
`embed_key` 为空时复用 `chat_key`（`app/settings.py:108 runtime_keys`）。

### 3.18 `POST /api/config`（`app/api.py:243-256`）

```json
// 请求（只传要改的字段）
{"chunk_size": 120, "chunk_overlap": 30}
// 响应
{"ok": true, "config": {…14 字段…}, "status": {…同 /api/status…}}
```

两道校验（**先于落盘**）：

| 条件 | 400 detail |
| --- | --- |
| `not 50 <= chunk_size <= 1000` | `片段长度须在 50 至 1000 之间。` |
| `not 0 <= chunk_overlap < size` | `重叠字数须满足 0 <= 重叠 < 片段长度。` |

`size` 取值逻辑：`patch.get("chunk_size", load_config().get("chunk_size", 180))`——
只传 `chunk_overlap` 时用当前已保存的 `chunk_size` 做上界。

响应里带完整 `status`，前端 `buildIndex` 拿到后可以直接刷新界面而不必再发一次 `/api/status`。

### 3.19 `GET /`（`app/api.py:282-286`）

```python
@app.get("/")
def index_page() -> Any:
    if not WEB_ENTRY.exists():
        return HTMLResponse(content=_MISSING_DIST, status_code=503)
    return FileResponse(WEB_ENTRY)
```

`WEB_ENTRY = web/dist/index.html`。dist 缺失时返回 503 + 中文指引页（含三步构建命令），
**不抛异常**——这样「只跑后端接口」的场景（自检、curl）不会因为没构建前端而整个挂掉。

### 3.20 `/static`（`app/api.py:291`）

```python
app.mount("/static", StaticFiles(directory=str(WEB_DIST), check_dir=False), name="static")
```

`check_dir=False` 是**必须的**：默认 `True` 时 `StaticFiles` 会在构造阶段检查目录，
dist 不存在就抛 `RuntimeError: Directory 'web/dist' does not exist`，
这会让 `import app.api` 直接失败 → `run.cmd` 起不来 → `tools/selfcheck.py` 也起不来。

实测：`GET /static/assets/index-D3qgyOn-.js` → 200，`Content-Type: text/javascript`。

## 四、前后端调用对应表

| 前端动作 | 调用的接口 | 文件:行 |
| --- | --- | --- |
| 首屏加载 | `GET /api/status` + `GET /api/docs` | `web/src/store.js:refresh` |
| 上传资料 | `POST /api/docs/upload`（FormData `files`） | `store.js:actions.upload` |
| 删除资料 | `DELETE /api/docs/{name}` | `store.js:actions.removeDoc` |
| 点资料名看全文 | `GET /api/docs/{name}/content` | `store.js:actions.openDoc` |
| 重新建库 | `POST /api/config` → `POST /api/index` → 轮询 `GET /api/index/progress` | `store.js:actions.buildIndex` |
| 提问 | `POST /api/chat` | `store.js:actions.send` |
| 改 k / 改模式 | `POST /api/session/params` | `store.js:actions.setK` / `setMode` |
| 清空对话 | `POST /api/session/new` | `store.js:actions.newSession` |
| 检索过程视图 | `GET /api/logs/last` | `store.js:actions.loadLastMessages` |
| 片段浏览 | `GET /api/chunks` | `store.js:actions.loadChunks` |
| 运行批量 | `POST /api/batch/run` → 轮询 `GET /api/batch/progress` | `store.js:actions.runBatch` / `pollBatch` |
| 导出 CSV | `POST /api/batch/export` | `store.js:actions.exportBatch` |
| 加载密钥 | `POST /api/keys` | `store.js:actions.applyKeys` |

## 五、curl 冒烟命令（可直接复制）

```powershell
# 状态
curl.exe -s http://127.0.0.1:8765/api/status

# 提问（rag）
curl.exe -s -X POST http://127.0.0.1:8765/api/chat -H "Content-Type: application/json" ^
  -d "{\"question\":\"普通图书最多同时借阅几本借多久？\",\"mode\":\"rag\",\"k\":3}"

# 片段浏览（中文 query 必须 URL 编码，PowerShell 下用 py 发更省事）
py -3.12 -X utf8 -c "import urllib.parse,urllib.request,json; p='/api/chunks?q='+urllib.parse.quote('续借'); print(json.load(urllib.request.urlopen('http://127.0.0.1:8765'+p))['total'])"

# 建库 + 轮询
curl.exe -s -X POST http://127.0.0.1:8765/api/index
curl.exe -s http://127.0.0.1:8765/api/index/progress
```

**坑**：`urllib` 直连中文 query 不编码会 `UnicodeEncodeError: 'ascii' codec can't encode`，
必须 `urllib.parse.quote(path, safe='/?=&')`。

## 六、交叉引用

- 路由如何触发下游逻辑 → `docs/03-后端设计/B00_后端架构总览.md`
- 请求体模型的字段定义 → `docs/03-后端设计/B01_模块清单与依赖关系.md`
- 错误文案与日志 → `docs/03-后端设计/B07_错误处理_日志_自检.md`
- 前端如何消费这些响应 → `docs/04-前端设计/U05_前端接口调用清单.md`
- 静态托管改造的完整背景 → `docs/02-技术栈/T02_前端依赖与运行环境.md`
