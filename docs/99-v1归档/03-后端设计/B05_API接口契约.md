# B05 API 接口契约

> ⚠️ **v1 历史归档（2026-11-01）**：本文描述的 `app/` 十四个模块已于 2026-11-01 随 v2 后端重构删除，
> 归档源码在 `.snapshots/_archive/v1-backend-removed-20261101`。本文仅作迁移参考与答辩时的「改造前」对照，
> **不作为现行实现依据**。现行后端见 `docs/02-重构设计/后端文档.md`（Java）与 `RAG文档.md`（Python）。

> 锚点：`app/api.py`（v1 单体 24 条路由与请求/响应形状）、`frontend/src/api/modules/*.ts`（现行调用方）、`frontend/src/api/normalize.ts`（字段兼容层）
>
> 本文分两半：
> - **第一~三章**＝v1 现行 Python 单体 `app/api.py` 的 24 条路由行为记录，用于回归自检与行为对齐。
> - **第四章**＝v2 现行契约，即 Vue 前端（`frontend/`）真正在调用的 28 个端点，Java 网关与 Python AI 服务必须按此实现。
>
> 最后核对：2026-11-01（前端 P1–P6 完成、旧 `web/` 已删除）

---

## 一、错误响应总则

| HTTP | 触发 | body |
| --- | --- | --- |
| 400 | 业务校验失败，抛 `AppError` | `{"detail": "中文说明"}` |
| 404 | 资料不存在 | `{"detail": "没有找到资料 xxx.md"}` |
| 422 | Pydantic 校验失败（缺参数/类型不对） | FastAPI 默认结构 |
| 503 | `frontend/dist` 未构建，访问 `/` | 中文 HTML 指引页（`app/api.py:263 _MISSING_DIST`） |

`app/api.py:20` 定义了 `AppError`，`:23` 起是统一的错误转换；`:28-256` 是 22 条 `/api/*` 业务路由；`:283` 是 `index_page`；`:292` 是 `app.mount("/static")`；`:295` 起是 `app_error_handler`。

### 1.1 v1 前端的错误取值方式（历史记录）

v1 前端 `web/src/api.js:8` 的实现是取 `detail` 字段：

```js
const detail = data && data.detail ? data.detail : `请求失败（HTTP ${response.status}）`;
throw new Error(detail);
```

> ⚠️ 该文件已随 `web/` 目录删除，此处仅作 v1 行为记录，**不要照抄**。

### 1.2 现行前端（`frontend/`）的错误取值方式

`frontend/src/api/http.ts` 的响应拦截器按统一信封解包：

- 响应体没有 `code` 字段 → 原样返回（兼容非信封接口）。
- `code === 0` → 拆出 `data` 返回业务层。
- `code !== 0` → 抛 `ApiError(code, message, httpStatus)`，`message` 直接展示给用户。
- HTTP 401 → 清 token + `emit('auth:expired')` + 跳登录页。
- HTTP 503 → `emit('system:degraded')` 并置顶状态横幅，**不抛异常**。

信封形状见 `docs/02-重构设计/00_项目架构规格.md` §3：`{ code, message, data, timestamp }`。

---

## 二、请求约定

### 2.1 通用

- 请求一律 JSON 外发：`Content-Type: application/json`，FastAPI 侧用 `ensure_ascii=False`，Starlette `JSONResponse` 负责编码。
- 上传按 `utf-8-sig` 解码（允许 BOM）；解码失败或正文为空直接进 `skipped`，不中断整批。
- 日志用 `encoding="utf-8", newline="\n"`（`app/api.py:77`）。

### 2.2 v1 路由总表（24 条）

| # | 方法 | 路径 | 处理函数 | 行号 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/status` | `status` | `:28` | 全站快照（见 3.1） |
| 2 | GET | `/api/docs` | `list_docs` | `:47` | 资料清单 |
| 3 | POST | `/api/docs/upload` | `upload_docs` | `:52` | multipart 字段名 `files` |
| 4 | DELETE | `/api/docs/{name}` | `remove_doc` | `:83` | 按文件名删除 |
| 5 | GET | `/api/docs/{name}/content` | `doc_content` | `:92` | 取原文 |
| 6 | GET | `/api/chunks` | `chunks` | `:100` | 支持 `source` / `q` |
| 7 | POST | `/api/chat` | `chat` | `:118` | 支持 rag / direct / both |
| 8 | POST | `/api/session/params` | `session_params` | `:131` | 改 mode 或 k 会清空 history |
| 9 | POST | `/api/session/new` | `session_new` | `:140` | 清空对话，保留 mode/k |
| 10 | POST | `/api/index` | `build_index` | `:147` | 触发建库 |
| 11 | GET | `/api/index/progress` | `index_progress` | `:156` | 读 `_BUILD_STATE` |
| 12 | POST | `/api/batch/run` | `batch_run` | `:163` | 批量对照，运行中拒绝 |
| 13 | GET | `/api/batch/progress` | `batch_progress` | `:173` | 10 行结果 |
| 14 | POST | `/api/batch/export` | `batch_export` | `:202` | CSV 8 列带 BOM |
| 15 | GET | `/api/batch/questions` | `batch_questions` | `:211` | questions.csv + keywords.csv |
| 16 | POST | `/api/keys` | `set_keys` | `:226` | 密钥只进内存 |
| 17 | POST | `/api/config` | `set_config` | `:243` | 改 chunk_size / overlap |
| 18 | GET | `/api/logs/last` | `logs_last` | `:259` | 最近一次日志 |
| 19 | GET | `/api/eval/set` | `eval_set` | `:268` | 评测问题集 |
| 20 | GET | `/api/eval/keywords` | `eval_keywords` | `:275` | 判分关键词 |
| 21 | POST | `/api/selfcheck` | `selfcheck` | `:282` | 自检 |
| 22 | GET | `/api/version` | `version` | `:290` | 版本 |
| 23 | GET | `/` | `index_page` | `:283` | 服务 `frontend/dist/index.html` |
| 24 | GET | `/static` | `StaticFiles` | `:292` | 指向 `frontend/dist` |

> v1 前端已随 `web/` 删除，上表只作 Python 侧回归参照；现行前端不用这些路由，全部走第四章的 `/api/v1/*`。

---

## 三、v1 关键接口细节（回归自检用）

### 3.1 `GET /api/status`（`app/api.py:28-46`）

返回全站快照：`provider`、`mock`、`chunk_size`（默认 180）、`chunk_overlap`（默认 30）、`top_k`（默认 3）、`docs`（6 份，含 `name` / `chars` / `chunks` / `verified`）、`doc_count`、`ready`、`stale`、`chunks`、`message`、`manifest`、`build`（`stage` / `done` / `total` / `docs` / `chunks` / `message` / `error`）、`session`、`has_keys`、`k_range`（`[1, 5]`）、`config`、`examples`（questions.csv 前 4 题）。

### 3.2 `POST /api/docs/upload`（`app/api.py:52-82`）

multipart 字段名 `files`。五道校验，任一不过进 `skipped` 而不中断整批：

1. 后缀 ∈ `{.md, .txt}`
2. 大小 ≤ 2MB
3. `utf-8-sig` 可解码
4. 正文非空
5. `Path(name).name` 防路径穿越

### 3.3 `GET /api/chunks`（`app/api.py:100-117`）

返回 `{ chunks: [{ chunk_id, source, start, end, verified, text, position }], size, overlap, total }`。
`q=续借` 实测 4 条（D02-C001、D02-C002、D04-C003、D06-C002）。
D02-C001（start 0, end 180）与 D02-C002（start 150, end 294）位置重叠 30 字 —— 拓展 B 的验收依据。

### 3.4 `POST /api/chat`（`app/api.py:118-130`）

`mode="both"` 顶层取 rag 结果，另加 `rag` 与 `direct` 两个完整对象。
`mode` 非法 → 400「回答模式只能是 rag、direct 或 both。」
`k` 越界 → 400「每次取回片段数量须在 1 至 5 之间。」

### 3.5 `POST /api/batch/run`（`app/api.py:163-172`）

`total = 20`（10 题 × 2 模式）；运行中再调 → 400「批量测试正在运行中。」
实测 `stats.rag = 10`、`stats.direct = 1`（任务 5 验收第 ② 项数据）。

### 3.6 `POST /api/config`（`app/api.py:243-258`）

两道校验：

| 条件 | 400 detail |
| --- | --- |
| `not 50 <= chunk_size <= 1000` | 「片段长度须在 50 至 1000 之间。」 |
| `not 0 <= chunk_overlap < size` | 「重叠字数须满足 0 <= 重叠 < 片段长度。」 |

`size` 取 body 的 `chunk_size`，缺省回落 `load_config()["chunk_size"]`（180）；`chunk_overlap` 同样回落配置值。
改完返回完整 `status`，前端据此判断是否需要重新建库。

### 3.7 `GET /`（`app/api.py:283-287`）

```python
@app.get("/")
def index_page() -> Any:
    if not WEB_ENTRY.exists():
        return HTMLResponse(content=_MISSING_DIST, status_code=503)
    return FileResponse(WEB_ENTRY)
```

`WEB_ENTRY = frontend/dist/index.html`（`app/settings.py` 的 `WEB_DIR = ROOT / "frontend"`）。
dist 缺失时返回 503 + 中文指引页（含三步构建命令，`app/api.py:263 _MISSING_DIST`），**不抛异常** —— 这样「只跑后端接口」的场景（自检、curl）不会因为没构建前端而整个挂掉。

### 3.8 `/static`（`app/api.py:292`）

```python
app.mount("/static", StaticFiles(directory=str(WEB_DIST), check_dir=False), name="static")
```

`check_dir=False` 是**必须的**：默认 `True` 时 `StaticFiles` 会在构造阶段检查目录，dist 不存在就抛
`RuntimeError: Directory 'frontend/dist' does not exist`，这会让 `import app.api` 直接失败 →
`run.cmd` 起不来 → `tools/selfcheck.py` 也起不来。

实测：`GET /static/index.html` → 200，返回 `frontend/dist/index.html`。

---

## 四、前后端调用对应表

### 4.1 v1（`web/`，已删除，仅作历史对照）

| 动作 | 接口 | 文件 |
| --- | --- | --- |
| 首屏加载 | `GET /api/status` + `GET /api/docs` | `web/src/store.js:refresh` |
| 上传资料 | `POST /api/docs/upload`（FormData `files`） | `store.js:actions.upload` |
| 删除资料 | `DELETE /api/docs/{name}` | `store.js:actions.removeDoc` |
| 查看原文 | `GET /api/docs/{name}/content` | `store.js:actions.openDoc` |
| 重建索引 | `POST /api/config` → `POST /api/index` → `GET /api/index/progress` | `store.js:actions.buildIndex` |
| 提问 | `POST /api/chat` | `store.js:actions.send` |
| 改模式 / k | `POST /api/session/params` | `store.js:actions.setK` / `setMode` |
| 清空对话 | `POST /api/session/new` | `store.js:actions.newSession` |
| 恢复上次消息 | `GET /api/logs/last` | `store.js:actions.loadLastMessages` |
| 批量对照 | `POST /api/batch/run` → `GET /api/batch/progress` → `POST /api/batch/export` | `store.js:actions.runBatch` |
| 设置密钥 | `POST /api/keys` | `store.js:actions.setKeys` |

> ⚠️ 上表所有 `web/src/*.js` 路径均已不存在（`web/` 于 2026-11-01 删除）。**现行实现看 4.2。**

### 4.2 现行 `frontend/`（前缀 `/api/v1`）

| 动作 | 接口 | 调用文件 |
| --- | --- | --- |
| 登录 | `POST /auth/login` | `frontend/src/api/modules/auth.ts` |
| 取用户信息 | `GET /auth/profile` | `auth.ts` |
| 会话列表 | `GET /conversations` | `frontend/src/api/modules/chat.ts` |
| 新建会话 | `POST /conversations`（body `{title}`） | `chat.ts` |
| 删除会话 | `DELETE /conversations/{id}` | `chat.ts` |
| 消息历史 | `GET /conversations/{id}/messages` | `chat.ts` |
| 清空对话（F10） | `DELETE /conversations/{id}/messages` | `chat.ts` |
| 检索轨迹 | `GET /messages/{id}/trace` | `chat.ts` |
| 流式提问（SSE） | `POST /chat/stream`（body `{conversationId, question, mode, k}`） | `chat.ts` + `frontend/src/api/sse.ts` |
| 资料列表 | `GET /documents` | `frontend/src/api/modules/knowledge.ts` |
| 上传资料 | `POST /documents`（FormData 字段名 `files`） | `knowledge.ts` |
| 改资料 | `PUT /documents/{id}` | `knowledge.ts` |
| 删资料 | `DELETE /documents/{id}` | `knowledge.ts` |
| 索引状态（F03） | `GET /index/status` | `knowledge.ts` |
| 触发重建 | `POST /index/rebuild`（body `{chunkSize, overlap}`） | `knowledge.ts` |
| 建库进度 | `GET /index/tasks/{id}`（1s 轮询） | `knowledge.ts` |
| 片段浏览 | `GET /chunks`（query `docId` / `q` / `kind`） | `knowledge.ts` |
| 评测题目 | `GET /eval/questions` | `frontend/src/api/modules/eval.ts` |
| 发起批量 | `POST /eval/batch` | `eval.ts` |
| 批量结果 | `GET /eval/runs/{id}` | `eval.ts` |
| 历史评测 | `GET /eval/runs` | `eval.ts` |
| 提交反馈（C1） | `POST /messages/{id}/feedback` | `eval.ts` |
| 反馈统计 | `GET /feedback/summary` | `eval.ts` |
| 候选池 | `GET /eval/candidates` | `eval.ts` |
| 候选决策 | `POST /eval/candidates/{id}/decision`（body `{status}`） | `eval.ts` |
| 创建实验（E3） | `POST /eval/experiments`（body `{name, axes}`） | `eval.ts` |
| 实验进度 | `GET /eval/experiments/{id}` | `eval.ts` |
| 实验报告 | `GET /eval/experiments/{id}/report` | `eval.ts` |

> ⚠️ `/eval/questions`、`/eval/candidates`、`/eval/candidates/{id}/decision`、`/eval/experiments*`、`/feedback/summary`、`/messages/{id}/feedback` 这 6 组**不在** `docs/02-重构设计/00_项目架构规格.md` §7.3 的 15 条里，属答辩套餐 B1（追问推荐）/ C1（反馈闭环）/ E3（参数实验）扩展。**后端必须一并实现**，否则前端评测页四页签无数据。
>
> 契约细节（SSE 五类事件、字段双形状兼容、状态白名单）见 `frontend/src/api/normalize.ts` 与 `docs/02-重构设计/00_项目架构规格.md` §7.5。

---

## 五、curl 自检命令

```bash
# 全站快照
curl.exe -s http://127.0.0.1:8765/api/status

# 提问（JSON body）
curl.exe -s -X POST http://127.0.0.1:8765/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"续借有什么规定？\",\"mode\":\"rag\",\"k\":3}"

# 片段过滤（观察 overlap）
curl.exe -s "http://127.0.0.1:8765/api/chunks?q=续借"
```

> Windows cmd 用 `^` 续行；PowerShell 用反引号 `` ` ``；URL 里的中文要 `curl.exe --data-urlencode` 或先 percent-encode。

---

## 六、与其他文档的关系

- 统一信封、SSE 协议、错误码表 → `docs/02-重构设计/00_项目架构规格.md`
- v1 模块职责与调用链 → `docs/03-后端设计/B00_后端架构总览.md`
- v2 Java 侧编排与降级 → `docs/02-重构设计/后端文档.md`
- v2 Python 侧检索与生成 → `docs/02-重构设计/RAG文档.md`
- 前端 mock 行为参照 → `frontend/src/mocks/handlers.ts`（同 28 端点）
