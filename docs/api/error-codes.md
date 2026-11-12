# 小忆 RAG 问答系统 · 错误码表

> **状态**：J0 契约冻结版
> **配套契约**：[`openapi-public.yaml`](./openapi-public.yaml)、[`openapi-internal.yaml`](./openapi-internal.yaml)、[`envelope.schema.json`](./envelope.schema.json)
> **唯一源头**：本表与两份 YAML 共同构成契约。YAML 的 `x-error-codes` 是本表的索引；本表是 `message` 文案与 HTTP 状态码的唯一权威。

---

## 1. 信封与错误响应

除 SSE 端点外，**所有响应（含错误）都包统一信封**：

```json
{ "code": 0, "message": "success", "data": {}, "timestamp": 1730000000 }
```

失败时：

```json
{ "code": 40401, "message": "资料不存在", "data": null, "timestamp": 1730000000 }
```

三条硬规则：

1. `code === 0` ⟺ 成功。`code !== 0` 时 `data` **恒为 `null`**，不是 `{}`、不是 `[]`。
2. `message` 在成功时固定为 `"success"`；失败时用本表「文案」列的**原文**，前端会直接展示，不得改写、不得拼接堆栈。
3. `timestamp` 是 **Unix 秒**（`integer`），不是毫秒、不是字符串日期。

**SSE 例外**：`POST /api/v1/chat/stream` 与 `POST /internal/v1/chat/stream` 的每一帧 `data:` 是独立 JSON，不包信封。流内错误走 `event: error` 帧：

```
event: error
data: {"code":50001,"message":"模型生成超时","fallback":"direct"}
```

`fallback: "direct"` 表示 Java 已自动降级为直答，前端可继续展示；无 `fallback` 表示流已终止。

---

## 2. HTTP 状态码 ↔ 业务码

业务码表达「错在哪」，HTTP 状态码表达「粗粒度类别」。两者**必须同步**，不允许业务码是 40001 而 HTTP 回 200。

| HTTP | 区间 | 含义 | 前端行为 |
|---|---|---|---|
| 200 | `0` | 成功 | 取 `data` |
| 400 | `400xx` | 参数校验失败 | 表单行内报错 |
| 401 | `401xx` | 未认证 / 令牌失效 | 清 token，跳登录（`auth:expired`） |
| 403 | `401xx` | 已认证但无权限 | 提示无权访问 |
| 404 | `404xx` | 资源不存在 | 提示并刷新列表 |
| 409 | `409xx` | 业务状态冲突 | 提示当前不可操作 |
| 500 | `500xx` | 服务内部错误 | 通用失败提示 |
| 501 | `50101` | 尚未实现 | 提示功能未开放 |
| 503 | `503xx` | AI 侧不可用 | 全局降级横幅（`system:degraded`） |

**唯一例外**：`50101` 允许回 HTTP 200 或 501（J1 阶段 26 条未实现路由的占位行为），两种都必须带完整信封。

---

## 3. 成功码

| code | message | 说明 |
|---|---|---|
| `0` | `success` | 一切成功。无其它成功码，不设 `200`、`1` 之类的变体。 |

---

## 4. 参数校验 `400xx`

| code | message（原文，不得改写） | HTTP | 触发条件 | 相关端点 |
|---|---|---|---|---|
| `40001` | `参数不合法` | 400 | 通用参数校验失败；`username` 为空时用 `用户名不能为空` | 全部有请求体的端点 |
| `40002` | `片段长度需在 50-1000 之间` | 400 | `chunkSize < 50` 或 `chunkSize > 1000`，或非整数 | `POST /index/rebuild`、`POST /eval/experiments` |
| `40003` | `重叠字数必须小于片段长度` | 400 | `overlap < 0` 或 `overlap >= chunkSize` | `POST /index/rebuild`、`POST /eval/experiments` |
| `40004` | `参数矩阵为空` | 400 | 实验轴笛卡尔积展开为 0 组（含全部组合都满足 `overlap >= chunkSize` 被跳过的情况） | `POST /eval/experiments` |

**`40001` 的特例文案**：登录时 `username` 为空，message 必须是 `用户名不能为空`（不是 `参数不合法`）。其余场景用 `参数不合法`，具体字段名由后端日志承载，不进 `message`。

**编号分配的历史差异**：早期开发阶段的 J4 任务说明曾把 `40001`/`40002` 分配给 chunkSize/overlap 校验，与前端 mock 的编号相反。**以本表为准**：`40002` = chunkSize 越界、`40003` = overlap 越界。理由：前端 `apps/web/src/mocks/handlers.ts:336-337` 与 `apps/web/test/` 已按此编号断言，改编号会打破既有测试。

---

## 5. 认证与授权 `401xx`

| code | message | HTTP | 触发条件 | 相关端点 |
|---|---|---|---|---|
| `40100` | `登录已过期` | 401 | Bearer token 缺失、格式错、签名错、已过期 | 除 `/auth/login` 外的全部对外端点 |
| `40101` | `无权访问该资源` | 403 | 已认证但资源不属于当前用户（会话/消息越权） | 会话与消息类端点 |
| `40102` | `内部令牌无效` | 401 | `X-Internal-Token` 缺失或与 `INTERNAL_TOKEN` 不匹配 | 内部 8 条端点 |

`40100` 是前端唯一会触发**自动登出**的码：`apps/web/src/api/http.ts` 收到 401 后清 `localStorage['xiaoyi.token']` 并广播 `auth:expired`。

`40102` 只在 `backend/ai-api/` 侧产生，Java 收到后应记 WARN 并转 `50301` 对外，**不得把 `内部令牌无效` 透给前端**。

---

## 6. 资源不存在 `404xx`

| code | message | HTTP | 触发条件 | 相关端点 |
|---|---|---|---|---|
| `40401` | `资料不存在` | 404 | `documents/{id}` 查无此文档（含已删除） | `PUT/DELETE /documents/{id}`、`GET /internal/v1/documents/{id}/status` |
| `40402` | `任务不存在` | 404 | `index/tasks/{id}` 查无此任务，或任务已被 GC | `GET /index/tasks/{id}`、`GET /internal/v1/ingest/{task_id}` |
| `40403` | `评测记录不存在` | 404 | `eval/runs/{id}` 查无此批次 | `GET /eval/runs/{id}` |
| `40404` | `候选不存在` | 404 | `eval/candidates/{id}` 查无此候选 | `POST /eval/candidates/{id}/decision` |
| `40405` | `实验不存在` | 404 | `eval/experiments/{id}` 查无此实验 | `GET /eval/experiments/{id}`、`GET /eval/experiments/{id}/report` |
| `40406` | `会话不存在` | 404 | `conversations/{id}` 查无此会话 | `DELETE /conversations/{id}`、`GET /conversations/{id}/messages`、`DELETE /conversations/{id}/messages` |
| `40407` | `消息不存在` | 404 | `messages/{id}` 查无此消息 | `GET /messages/{id}/trace`、`POST /messages/{id}/feedback` |

**`GET /messages/{id}/trace` 的宽松约定**：消息存在但尚无检索轨迹（纯 `direct` 模式产出）时，**不报 `40407`**，回 `{code: 0, data: null}`。只有消息本身不存在才报 `40407`。前端 `apps/web/src/api/modules/chat.ts:62` 的返回类型是 `Promise<RetrievalTrace | null>`，依赖此约定。

---

## 7. 业务冲突 `409xx`

| code | message | HTTP | 触发条件 | 相关端点 |
|---|---|---|---|---|
| `40901` | `实验进行中，提问暂不可用` | 409 | 有 `status === 'RUNNING'` 的参数实验时发起问答 | `POST /chat/stream` |
| `40902` | `已有实验在执行` | 409 | 创建新实验时已有实验在跑（实验串行，全局互斥） | `POST /eval/experiments` |
| `40903` | `已有建库任务在执行` | 409 | 发起建库时已有 `PENDING`/`RUNNING` 的建库任务（建库串行） | `POST /index/rebuild` |

这三条都是**互斥锁**语义，不是「参数错」。前端收到后应提示「请等待当前任务完成」，而不是让用户改参数重试。

`40901` 的判定必须在 SSE 建流**之前**：一旦已经回 `200 text/event-stream`，就不能再改成 409 了。

---

## 8. 服务内部 `500xx`

| code | message | HTTP | 触发条件 |
|---|---|---|---|
| `50000` | `服务内部错误` | 500 | 兜底。未捕获异常、DB 异常、序列化失败等一律归此码 |
| `50001` | `模型生成失败` | 500 | LLM 调用失败 / 超时 / 返回为空；`fallback: "direct"` 时降级为直答 |

`50000` 的 `message` 固定为 `服务内部错误`，**不得**把异常堆栈、SQL、类名写进 `message`。细节走服务端日志与 `audit_log` 表。

`50001` 出现在 SSE 流内时，`data` 里可带 `fallback: "direct"`；出现在普通端点（如 `POST /eval/batch`）时按普通 500 处理。

---

## 9. 未实现 `50101`

| code | message | HTTP | 触发条件 |
|---|---|---|---|
| `50101` | `尚未实现` | 200 或 501 | J1 阶段 28 条路由已挂载但业务未写，Controller 方法抛 `ApiException(50101, "尚未实现")` |

存在的意义：让 `tests/J1-skeleton/test_envelope_all_routes.py` 能在业务为空时验证「28 条路由全部返回合法信封」。J2 之后本码应逐步消失；J6 联调完成时对外 28 条中不应再有 `50101`。

---

## 10. AI 降级 `503xx`

| code | message | HTTP | 触发条件 |
|---|---|---|---|
| `50301` | `AI 服务不可用` | 503 | `backend/ai-api/` 不可达、`/internal/v1/health` 连续失败、熔断打开 |

前端 `apps/web/src/api/http.ts` 收到 503 后广播 `system:degraded`，页面顶部出降级横幅。

**与 `50001` 的区别**：`50001` 是「AI 服务活着但这次生成失败」（可重试）；`50301` 是「AI 服务整体不可用」（重试无意义，应等熔断恢复）。

---

## 11. 端点 → 错误码索引

对外 28 条。下表只列**业务语义相关**的码。

**全局兜底码 `50000`**：未捕获异常对任何端点都可能发生，故 `50000` 适用于全部 28 条，
**不在下表逐条重复**；两份 YAML 的每个 operation 的 `x-error-codes` 都显式列了它，
便于生成器产出完整的错误联合类型。下表只列**业务语义相关**的码。

| # | 端点 | 可能的错误码 |
|---|---|---|
| 1 | `POST /api/v1/auth/login` | `40001` |
| 2 | `GET /api/v1/auth/profile` | `40100` |
| 3 | `GET /api/v1/conversations` | `40100` |
| 4 | `POST /api/v1/conversations` | `40001`、`40100` |
| 5 | `DELETE /api/v1/conversations/{id}` | `40100`、`40406` |
| 6 | `GET /api/v1/conversations/{id}/messages` | `40100`、`40406` |
| 7 | `DELETE /api/v1/conversations/{id}/messages` | `40100`、`40406` |
| 8 | `POST /api/v1/chat/stream` | `40001`、`40100`、`40901`、`50001`、`50301` |
| 9 | `GET /api/v1/messages/{id}/trace` | `40100`、`40407` |
| 10 | `GET /api/v1/documents` | `40100` |
| 11 | `POST /api/v1/documents` | `40100`、`40001` |
| 12 | `PUT /api/v1/documents/{id}` | `40001`、`40100`、`40401` |
| 13 | `DELETE /api/v1/documents/{id}` | `40100`、`40401` |
| 14 | `GET /api/v1/index/status` | `40100` |
| 15 | `POST /api/v1/index/rebuild` | `40002`、`40003`、`40100`、`40903`、`50301` |
| 16 | `GET /api/v1/index/tasks/{id}` | `40100`、`40402` |
| 17 | `GET /api/v1/chunks` | `40001`、`40100` |
| 18 | `GET /api/v1/eval/questions` | `40100` |
| 19 | `POST /api/v1/eval/batch` | `40001`、`40100`、`50001`、`50301` |
| 20 | `GET /api/v1/eval/runs` | `40100` |
| 21 | `GET /api/v1/eval/runs/{id}` | `40100`、`40403` |
| 22 | `POST /api/v1/messages/{id}/feedback` | `40001`、`40100`、`40407` |
| 23 | `GET /api/v1/feedback/summary` | `40100` |
| 24 | `GET /api/v1/eval/candidates` | `40100` |
| 25 | `POST /api/v1/eval/candidates/{id}/decision` | `40001`、`40100`、`40404` |
| 26 | `POST /api/v1/eval/experiments` | `40001`、`40002`、`40003`、`40004`、`40100`、`40902` |
| 27 | `GET /api/v1/eval/experiments/{id}` | `40100`、`40405` |
| 28 | `GET /api/v1/eval/experiments/{id}/report` | `40100`、`40405` |

内部 8 条：

| # | 端点 | 可能的错误码 |
|---|---|---|
| 1 | `POST /internal/v1/chat/stream` | `40001`、`40102`、`50001`、`50301` |
| 2 | `POST /internal/v1/retrieve` | `40001`、`40102`、`50000` |
| 3 | `POST /internal/v1/documents/parse` | `40001`、`40002`、`40003`、`40102`、`50000` |
| 4 | `GET /internal/v1/ingest/{task_id}` | `40102`、`40402`、`50000` |
| 5 | `GET /internal/v1/documents/{id}/status` | `40102`、`40401`、`50000` |
| 6 | `GET /internal/v1/index/status` | `40102`、`50000`、`50301` |
| 7 | `POST /internal/v1/eval/batch` | `40001`、`40102`、`50000` |
| 8 | `GET /internal/v1/health` | `40102`、`50301` |

---

## 12. 上传的「非错误」通道

`POST /api/v1/documents` 是批量上传，**单份文件不合规不算接口失败**。整体仍回 `{code: 0}`，不合规的文件进 `data.skipped[]`：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "accepted": [ { "id": "D01", "name": "01_活动说明.md", "...": "..." } ],
    "skipped": [
      { "name": "photo.png", "reason": "只接受 .md / .txt 文件" },
      { "name": "huge.md", "reason": "文件超过 2MB" },
      { "name": "empty.txt", "reason": "文件没有正文" }
    ]
  },
  "timestamp": 1730000000
}
```

`reason` 的四个固定取值（不得改写）：

| reason | 判定 |
|---|---|
| `只接受 .md / .txt 文件` | 后缀不在 `{.md, .txt}` |
| `文件超过 2MB` | `size > 2 * 1024 * 1024` |
| `文件没有正文` | 去空白后长度为 0 |
| `文件编码不是 UTF-8` | 无法按 UTF-8 解码 |

**只有一种情况整批失败**：`files` 字段缺失或为空 → `40001`。其余一律走 `skipped`。

文件名含路径分隔符（`../`、`..\`、`/`）时，按 `Path(name).getFileName()` 截取末段后再校验，不报错。

---

## 13. Java 侧异常映射（`GlobalExceptionHandler`）

| 异常 | 业务码 | HTTP |
|---|---|---|
| `ApiException(code)` | 原样透出 `code` | 按 §2 表格由 `code` 区间推导 |
| `MethodArgumentNotValidException` | `40001` | 400 |
| `ConstraintViolationException` | `40001` | 400 |
| `HttpMessageNotReadableException` | `40001` | 400 |
| `MaxUploadSizeExceededException` | `40001` | 400 |
| `AccessDeniedException` | `40101` | 403 |
| `NoResourceFoundException` / `NoHandlerFoundException` | `40401` | 404 |
| `Exception`（兜底） | `50000` | 500 |

兜底分支必须 `log.error` 记录原始异常与 traceId，但响应体只留 `服务内部错误`。

---

## 14. 前端消费约定

| 收到 | 前端动作 | 代码位置 |
|---|---|---|
| `code === 0` | 返回 `data` | `apps/web/src/api/http.ts` 响应拦截器 |
| `code !== 0` | 抛 `ApiError(code, message, status, data)` | 同上 |
| HTTP 401 | 清 `localStorage['xiaoyi.token']` + `emit('auth:expired')` | 同上 |
| HTTP 503 | `emit('system:degraded')` | 同上 |
| `40901` | 问答输入框置禁用态 + 提示 | `apps/web/src/features/chat/` |
| `50101` | 提示「功能未开放」 | 全局 |

`ApiError` 的 `message` 直接取自信封的 `message`，前端不再二次翻译 —— 所以本表的文案就是用户看到的文案，改动需同步前后端。
