# 星河读书会 · 个人资料助手 — 文档总览

> 对应《实验一：RAG 个人知识库助手实验指导书》（广东东软学院，设计性实验，6 学时）。
> 本仓库是该实验的**完整可运行实现**：前端 `frontend/`（Vue 3 + Vite 5 + TypeScript，已落地）；
> 后端 v2 为 **Java 业务网关（`server-java/`）+ Python AI 服务（`server-ai/`）**：J0–J4 与 A1–A3 全部完成，套餐一亮点包的 **N1–N6 全部完成并验收**（未完成项：无）。
> **最后核对**：2026-11-09（N6 收口：两档根门禁 11/11 阶段 `partial=false`——J2 35 / J3 38 / J5 41 / A2 37 / A3 31 等；Java `mvn verify` 88 项 / 前端 316 项全绿；99 份上传前置拦截 + 真实 provider 的查询改写端到端取证）

---

## 一、四个目录各管什么

```
docs/
├─ 01-功能规格/    指导书 F1~F11 逐条功能规格 + 提示词汇总 + 验收清单   ← 先读这里知道要做什么
├─ 02-技术栈/      用了什么、什么版本、为什么不用别的                     ← 知道用什么做
├─ 02-重构设计/    ★ v2 架构规格 + 前端/后端/RAG 三份设计 + 两份开发提示词  ← 重构的唯一事实来源
├─ 03-架构评审/    架构快照 + 企业级评分基线 + 评审提示词 + 评审结论      ← 判断"够不够企业级"
└─ 99-v1归档/      v1 后端（Python 单体 app/）的 9 份设计与依赖文档       ← 只作「改造前」对照
```

> ⚠️ **文档体系状态说明（2026-11-01）**：本项目已进入架构重构（Java 业务服务 + Python AI 服务 + 前端对接 Java 网关），新设计以 **`02-重构设计/00_项目架构规格.md`** 为唯一事实来源。
>
> **已下线的两批 v1 文档**：
> 1. 原 `04-前端设计/`（U00–U05）与 `05-端到端联调/`（I01–I03）描述的 v1 前端 `web/` 已删除，这 9 份文档同步下线，归档在 `.snapshots/_archive/docs-v1-frontend-removed-20261101`（不进版本库）。现行前端文档见 `frontend/README.md` 与 `02-重构设计/前端文档.md`。
> 2. 原 `03-后端设计/`（B00–B07）与 `02-技术栈/T01` 描述的 v1 Python 单体 `app/`（14 模块 / 1921 行）已于 2026-11-01 删除，这 9 份文档整体移入 **`99-v1归档/`** 并加「v1 历史归档」警示块；归档源码在 `.snapshots/_archive/v1-backend-removed-20261101`（不进版本库）。现行后端见 `02-重构设计/后端文档.md`（Java）、`RAG文档.md`（Python）与 `04_后端开发提示词.md`（启动顺序与门禁）。
>
> `01-功能规格` 是需求基线，**继续有效，验收标准不变**。

| 目录 | 面向 | 读法 |
| --- | --- | --- |
| `01-功能规格` | 「要做到什么」 | 从指导书任务出发，按 F 编号查 |
| `02-技术栈` | 「用什么做」 | 一张总表看全貌，一份前端明细查版本与约束 |
| `02-重构设计` | 「架构怎么定」 | 00 规格看全局，三份展开文档看前端/后端/RAG，两份提示词按阶段施工 |
| `03-架构评审` | 「够不够企业级」 | 先跑快照脚本，再按 8 维度基线打分，最后分三轮让 LLM 评审 |
| `99-v1归档` | 「改造前长什么样」 | 只在需要对照或写报告「改造前后」时查 |

## 二、全部文档索引

### 01-功能规格（13 份）

指导书要求的功能点，逐条拆成「前端表现 + 后端逻辑 + 验收点」。

| 文档 | 一句话 |
| --- | --- |
| [F01_资料管理.md](01-功能规格/F01_资料管理.md) | 资料列表、上传 .md/.txt（≤2MB）、删除、未核实标识、字数与片段数 |
| [F02_分块与建库.md](01-功能规格/F02_分块与建库.md) | 滑窗分块算法、片段长度/重叠参数、分批嵌入、原子写索引、拓展B 要点 |
| [F03_状态提示.md](01-功能规格/F03_状态提示.md) | manifest 比对原理、索引五层校验、「需要重新建库」三态徽章 |
| [F04_提问与回答.md](01-功能规格/F04_提问与回答.md) | 消息拼装结构、system/user 分层、direct 模式、日志字段 |
| [F05_来源标注.md](01-功能规格/F05_来源标注.md) | 来源卡五要素、编号映射、点击定位、幻觉引用剔除、诚实提示 |
| [F06_回答模式.md](01-功能规格/F06_回答模式.md) | 查资料 / 不查资料 / 两者对照 三种模式的分叉点与历史隔离 |
| [F07_检索数量.md](01-功能规格/F07_检索数量.md) | k 的取值 1–5、`select_top_k` 实现与三个陷阱 |
| [F08_检索过程.md](01-功能规格/F08_检索过程.md) | 全量排名表、`retrieved` 标记、第 k 行虚线、消息结构查看 |
| [F09_批量对照测试.md](01-功能规格/F09_批量对照测试.md) | 13 题 × 两模式、关键词初判规则、统计与 CSV 导出 |
| [F10_清空对话.md](01-功能规格/F10_清空对话.md) | 换 session_id 清历史、保留 mode/k |
| [F11_资料可信度.md](01-功能规格/F11_资料可信度.md) | 未核实资料标记、三道防线、夹带指令不执行、残余风险 |
| [PROMPTS_提示词汇总.md](01-功能规格/PROMPTS_提示词汇总.md) | 运行时 3 条提示词 + 开发用 Dev-1~7 + 报告记录要求 |
| [验收清单.md](01-功能规格/验收清单.md) | 任务1–5 + 拓展A/B + 报告逐项 checkbox、提交材料、自查 |

### 02-技术栈（2 份）

| 文档 | 一句话 |
| --- | --- |
| [T00_技术栈总表.md](02-技术栈/T00_技术栈总表.md) | v2 三端技术栈全表（Java 规划 / Python 规划 / 前端实测 24 项）+ **刻意不引入** 11 项及理由 |
| [T02_前端依赖与运行环境.md](02-技术栈/T02_前端依赖与运行环境.md) | node 21.7.1 硬约束下的版本选择矩阵、16 个 scripts、vite 配置逐段、构建产物 |

> v1 的 `T01_后端依赖与版本.md`（Python 包实测版本）已随 `app/` 删除移入 [`99-v1归档/02-技术栈/`](99-v1归档/02-技术栈/T01_后端依赖与版本.md)。

### 02-重构设计（9 份）

| 文档 | 一句话 |
| --- | --- |
| [00_项目架构规格.md](02-重构设计/00_项目架构规格.md) | **唯一事实来源**：三端拓扑、6 条架构铁律、29 条对外接口、8 条内部接口、SSE 事件协议、里程碑 |
| [前端文档.md](02-重构设计/前端文档.md) | `frontend/` 已落地的 SPA 设计：技术选型、路由、状态、三页契约 |
| [后端文档.md](02-重构设计/后端文档.md) | Java 业务服务：技术栈、聊天编排 5 步、建库编排 4 步、集成规范 |
| [RAG文档.md](02-重构设计/RAG文档.md) | Python AI 服务：离线管线、在线 7 步、防幻觉提示词、评估与安全 |
| [01_功能扩展清单.md](02-重构设计/01_功能扩展清单.md) | 三档套餐的功能清单与工期，明确不建议做的事 |
| [02_套餐方案_答辩亮点包.md](02-重构设计/02_套餐方案_答辩亮点包.md) | 已选定的答辩亮点包：B1 追问 / C1 反馈闭环 / E3 参数实验 / B3 结构化回答 |
| [03_前端开发提示词.md](02-重构设计/03_前端开发提示词.md) | P1–P6 分阶段开发手册与每阶段门禁（**已全部执行完毕**） |
| [04_后端开发提示词.md](02-重构设计/04_后端开发提示词.md) | **旧后端清除清单 + 技术栈启动顺序（Java 先）+ 根 `test/` 规范 + J0→J6/A1→A3 分阶段提示词与门禁**（H0–H4/P0–P8/A2/A3 均已执行）。注：文中「28 条对外接口」是 J0 当时的基线，`eval/candidates/export` 落地后为 29 条 |
| [05_后端开发提示词_亮点包后端.md](02-重构设计/05_后端开发提示词_亮点包后端.md) | **套餐一剩余后端的 N1–N6 提示词**：实验参数真生效、追问推荐、全局摘要卡、反馈闭环、结构化回答、收口（含现状证据与反模式清单） |

### 03-架构评审（7 份 + 1 脚本 + 1 归档目录）

判断「这套架构够不够企业级」。核心思路：**机器出事实，人出标准，LLM 只做判断**。

| 文档 | 一句话 |
| --- | --- |
| [README.md](03-架构评审/README.md) | 方法论：为什么直接问 LLM 会失败 + 三步法 + 四个防注水技巧 |
| [01_企业级基线.md](03-架构评审/01_企业级基线.md) | **8 维度 × 0–3 分评分表**（分层/契约/数据/安全/可观测/容错/可测/交付），每档都有「什么证据才算」 |
| [02_评审提示词.md](03-架构评审/02_评审提示词.md) | P1 架构符合性 / P2 后端完善度 / P3 前端完善度，三段可复制提示词（通用模板，含占位符） |
| [04_可直接粘贴的提示词.md](03-架构评审/04_可直接粘贴的提示词.md) | **本仓库专用版**，路径已写死，复制即执行；含 P0 开场自检、P4 最小版、P5 重构对比、纯聊天窗口版 |
| [05_P2P3_已填入P1结论.md](03-架构评审/05_P2P3_已填入P1结论.md) | P2 后端 / P3 前端提示词，P1 结论（14/24 + 3 个 P0）已内嵌，直接复制 |
| [06_后端施工单.md](03-架构评审/06_后端施工单.md) | **诊断转施工**：先定单用户/多用户，再三波次推进；第一波含可复制施工单与四项验收 |
| [07_前后端契约差异清单.md](03-架构评审/07_前后端契约差异清单.md) | **P0–P8 契约适配的落地记录**：8 个维度的旧/新行为对照 + A–G 验收结果 + 12 条验收期间修掉的真实缺陷 |
| [03_首轮评审结论.md](03-架构评审/03_首轮评审结论.md) | 实测结论 **14/24 分**，3 个 P0（资料越权、后门 token、Python 全局状态）均带行号 |
| [snapshot/架构快照.md](03-架构评审/snapshot/架构快照.md) | 机器生成，**不要手改**；290 行覆盖三端规模/端点/依赖/测试/反模式 |
| [evidence/index.md](03-架构评审/evidence/index.md) | **门禁报告归档**：24 份 JSON（H0–H4、J0–J4、P7/P8、A2/A3、四档对照），含大小、结论与 SHA256；由 `tools/archive_evidence.py` 生成，`test-artifacts/` 本身被 gitignore |
| `tools/arch_snapshot.py` | 快照生成器，零依赖，`python tools/arch_snapshot.py` 直接跑 |

### 99-v1归档（9 份）

> ⚠️ 全部加「v1 历史归档（2026-11-01）」警示块，**不作为现行实现依据**。源码归档在 `.snapshots/_archive/v1-backend-removed-20261101`。

| 文档 | 一句话 |
| --- | --- |
| [T01_后端依赖与版本.md](99-v1归档/02-技术栈/T01_后端依赖与版本.md) | 每个 Python 包的本机实测版本、用途、传递依赖、启动命令 |
| [B00_后端架构总览.md](99-v1归档/03-后端设计/B00_后端架构总览.md) | 14 个模块 1921 行的分层图、请求路径、为什么这样切 |
| [B01_模块清单与依赖关系.md](99-v1归档/03-后端设计/B01_模块清单与依赖关系.md) | 逐模块函数清单（签名+行号）、import 依赖图、无环验证 |
| [B02_数据模型与持久化.md](99-v1归档/03-后端设计/B02_数据模型与持久化.md) | chunk / index.json / manifest / JSONL 日志 / CSV 的完整字段与编码 |
| [B03_建库与检索链路.md](99-v1归档/03-后端设计/B03_建库与检索链路.md) | 分块 → 嵌入 → 原子写；余弦 → 排序 → 截取；mock 嵌入的三通道设计 |
| [B04_提示词与生成链路.md](99-v1归档/03-后端设计/B04_提示词与生成链路.md) | SYSTEM_PROMPT 七条逐条解释、`format_context`、引用校验、真实/模拟两条生成路径 |
| [B05_API接口契约.md](99-v1归档/03-后端设计/B05_API接口契约.md) | 24 条路由的入参/出参/错误码/实测响应，v1 契约记录 |
| [B06_离线模拟通道设计.md](99-v1归档/03-后端设计/B06_离线模拟通道设计.md) | 没有教师接口时怎么跑通：mock 嵌入 + 句子级证据匹配 + 10 题预置 direct 答案 |
| [B07_错误处理_日志_自检.md](99-v1归档/03-后端设计/B07_错误处理_日志_自检.md) | 三层错误、7 条索引文案、日志 19 字段、43 项自检分布、故障对照表 |

## 三、三条推荐阅读路线

### 路线 A：我要交作业，先跑起来

```
01-功能规格/验收清单.md          → 知道要交什么
        ↓
01-功能规格/ → 按 F 编号逐条核对表现        → 照着点、照着截图
        ↓
02-技术栈/T00_技术栈总表.md      → 报告里「技术选型」小节直接抄
```

命令（v2 前端已可独立运行，无需后端）：

```powershell
cd frontend; npm install; npm run dev; cd ..   # mock 模式 → http://127.0.0.1:5173
cd frontend; npm run test; cd ..               # 316 项前端测试（26 个 spec）
cd frontend; npm run gate -- P6 --build; cd .. # 四道门禁：lint + typecheck + test + build
cd frontend; npm run smoke; cd ..              # 7 项浏览器冒烟
cd frontend; npm run regress; cd ..            # 10 场景 CDP 回归
```

> v1 的 `run.cmd` / `py -3.12 -m app.api` / `tools\selfcheck.py` 已随旧后端删除。

#### 路线 A 补充：本机 MySQL 直连（不涉及 Docker 的最快路径）

`deploy/docker-compose.yml` 是交付形态，但它要求能拉到 `mysql:8.0` / `python:3.12-slim` / `maven` 等基础镜像。**拉不到镜像不等于跑不起来**：三个服务本来就可以直连本机已装好的 MySQL 8.0，表结构完全由 Java 启动时的 Flyway 迁移建立，不需要手工执行任何 `.sql`。如果要求服务确实在容器里，见下面的「路线 A 之二」。

```powershell
# 0) 一次性准备：本机已装 MySQL 8.0 并在 3306 监听
copy deploy\local-mysql.env.example deploy\local-mysql.env
#    填 MYSQL_PASSWORD，以及用 openssl rand -base64 48 / openssl rand -hex 32 生成的
#    AUTH_JWT_SECRET 与 INTERNAL_TOKEN；deploy/local-mysql.env 已被 .gitignore 忽略。

# 1) 建库（只 CREATE DATABASE IF NOT EXISTS，不建表）
python tools\local_mysql.py prepare

# 2) 起栈：Python(8000) + Java(8080)，Java 启动时 Flyway 自动跑 V1–V7
python tools\local_mysql.py up --timeout 180

# 3) 验收：双账号登录 + 13 张表 + Flyway 全 success，报告落 test-artifacts/local-mysql-verify.json
python tools\local_mysql.py verify

# 4) 端到端：上传 → 建库 → 轮询终态 → 断言 A/B 片段互不可见
python tools\local_mysql_smoke.py

# 5) 收工（只停本工具起的进程，不停 MySQL，不删库）
python tools\local_mysql.py down
# 需要重来一遍时：python tools\local_mysql.py drop-db --yes
```

要点：

- **表结构来源唯一**：`server-java/src/main/resources/db/migration/V1–V7`。`prepare` 只负责建空库，`up` 之后日志里应出现 `Successfully applied 7 migrations to schema ... now at version v7`，`verify` 会核对 13 张表（含 `flyway_schema_history`）。不要手工 `source` 迁移 SQL —— 那会让 Flyway 的校验和对不上。
- **库名必须独立**：默认 `xiaoyi_rag_local_gate`，脚本强制以 `_gate` / `_test` 结尾，避免误连开发库 `xiaoyi_rag`。
- **密钥是硬门槛**：`AUTH_JWT_SECRET` ≥ 32 UTF-8 字节、`INTERNAL_TOKEN` 非空、bootstrap 口令 12–72 字节，缺一个 `prepare` 就报错退出。这跟 Compose 里 `${AUTH_JWT_SECRET:?...}` 的 fail-fast 是同一条约束。
- **两档 provider**：`AI_MOCK=false` 走真实 Python（J0/J1/J2/J4/J6/J7/A1 用它跑）；`AI_MOCK=true` 用 Java 内置 MockAiClient（J3/J5 依赖它的 `[fail]` 标记与关键词打分）。
- **阶段节拍**：`INGEST_STAGE_DELAY_MS=1200` 给黑盒用例留出观测窗口（Java 侧 1s 轮询一次，低于 1000 会漏掉 `splitting/embedding/summarizing` 三个中间阶段）。生产/演示可以设 0 全速。
- **profile**：`P7_SPRING_PROFILES=gate-probe`（默认）才注册 `/__gate/throw`，J1 的「错误码 → HTTP 状态码」用例靠它真的走一遍 `GlobalExceptionHandler`；跑纯业务实例时显式设空值。

#### 路线 A 之二：Docker 起整套服务 + 宿主机 MySQL（2026-11-06 实测通过）

上一节是「全部跑在本机进程里」。如果要求三个服务确实在容器里、只有数据库在宿主机，用预构建镜像这份 compose —— 它不拉 `mysql:8.0`、也不在容器里跑 Maven / `npm ci`，只依赖三个能拉到的运行期基础镜像（`python:3.12-slim`、`eclipse-temurin:21-jre`、`nginx:1.27-alpine`）。

```powershell
# 1) 宿主机一次性准备
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS xiaoyi_rag_local_gate CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
python tools\local_mysql_grant_container.py     # 建 xiaoyi@'%' 并只授该库
cd server-java; mvn -q -DskipTests package; cd ..
cd frontend; npm run build:only; cd ..

# 2) 起栈（三个容器 + 一个 ai-state 卷）
$env:MYSQL_USER_FOR_CONTAINER = 'xiaoyi'
docker compose -f deploy/docker-compose.localdb-prebuilt.yml --env-file deploy/local-mysql.env up -d --build

# 3) 验收
docker compose -f deploy/docker-compose.localdb-prebuilt.yml --env-file deploy/local-mysql.env ps
python tools\compose_smoke.py                   # 走 nginx:8088，报告落 test-artifacts/compose-smoke.json

# 4) 收工（保留 ai-state 卷）
docker compose -f deploy/docker-compose.localdb-prebuilt.yml --env-file deploy/local-mysql.env down
```

三份 compose 的分工：

| 文件 | 数据库 | Java/前端怎么来 | 适用场景 |
| --- | --- | --- | --- |
| `deploy/docker-compose.yml` | `mysql:8.0` 容器 | 容器内 Maven 构建 + `npm ci` | 交付形态，**本机已实测通过**（169s，含 Flyway 从空库跑完 V1–V7） |
| `deploy/docker-compose.localdb.yml` | 宿主机 8.0.39 | 容器内 Maven 构建 + `npm ci` | 能拉 `maven`、拉不到 `mysql:8.0` 时用；**已实测通过**（`mvn package` 首次 379s，缓存后整套 build 约 3 分钟） |
| `deploy/docker-compose.localdb-prebuilt.yml` | 宿主机 8.0.39 | `Dockerfile.runtime` 拷宿主机 jar/dist | **日常首选**，秒级起栈（18.7s） |
| （无 compose）`tools/local_mysql.py` | 宿主机 8.0.39 | 本机进程，不涉及 Docker | 只要跑门禁、不需要容器 |

三份 compose 用同一个入口脚本，不必记命令：

```powershell
python tools\docker_deploy.py up --smoke                        # 默认 prebuilt（推荐）
python tools\docker_deploy.py --mode full up --smoke            # 容器内构建 + 宿主机库
python tools\docker_deploy.py --mode stack up --smoke           # 连 mysql:8.0 容器（不要加 --prepare-db）
python tools\docker_deploy.py status                            # 容器状态
python tools\docker_deploy.py down                              # 停栈，保留 ai-state 卷
python tools\docker_deploy.py build --push --registry registry.example.com/team --tag v1.0.0
```

`push` 只做 tag + push + 校验远端 digest，不会启动容器栈；没有 `--registry`/`IMAGE_REGISTRY` 时直接报错退出。已用本机临时 `registry:2` 实测：三个镜像推到 `127.0.0.1:5000/xiaoyi/xiaoyi-{python-ai,java-backend,frontend}:smoke`，`GET /v2/_catalog` 与 `tags/list` 都能查到，digest 与 `buildx imagetools inspect` 一致（证据在 `docs/03-架构评审/evidence/docker-deploy-prebuilt.json` 的 `pushedImages`）。

每次运行都写 `test-artifacts/docker-deploy-<mode>.json`（含耗时、镜像映射、容器健康、冒烟结果，不写任何口令）。`prebuilt` 模式会先跑 `mvn verify` + `npm run gate -- prebuilt --build`，除非加 `--skip-host-build`。

三份都已用 `docker compose --env-file deploy/local-mysql.env config --quiet` 校验通过，且都实跑过一遍：`prebuilt` 2.1s、`full` 22.3s（不含首次 379s 的 Maven 构建）、`stack` 169s（含 mysql 容器初始化 + 7 个迁移）。`stack` 模式下 `compose_smoke.py` 自动加 `--db-via-container`，走 `compose exec mysql` 查库（mysql 容器不发布 3306）。

要点：

- **必须带 `--env-file`**：`docker compose ps` / `config` 也要带，否则报 `required variable AUTH_JWT_SECRET is missing a value` —— 那些 `${VAR:?}` 是故意 fail-fast 的。
- **容器不能连 `root@localhost`**：`local-mysql.env` 里的 `MYSQL_USER=root` 只匹配 localhost，容器来源是 Docker 网关。`tools/local_mysql_grant_container.py` 建 `xiaoyi@'%'` 并只授 `xiaoyi_rag_local_gate.*`，compose 里默认 `${MYSQL_USER_FOR_CONTAINER:-xiaoyi}`。
- **`stack` 模式的 mysql 容器也拒绝 `MYSQL_USER=root`**：镜像 entrypoint 直接报 `MYSQL_USER and MYSQL_PASSWORD are for configuring a regular user and cannot be used for the root user` 并退出 1。所以 `deploy/docker-compose.yml` 的 mysql 与 java-backend 都用 `${MYSQL_USER_FOR_CONTAINER:-xiaoyi}`，root 只靠 `MYSQL_ROOT_PASSWORD` 初始化；`local-mysql.env` 里要同时给 `MYSQL_USER_FOR_CONTAINER` 与 `MYSQL_ROOT_PASSWORD`。
- **healthcheck 不能用 `/dev/tcp`**：`eclipse-temurin:21-jre` 的 `/bin/sh` 是 dash，`exec 3<>/dev/tcp/...` 会报 `Directory nonexistent`、容器恒 unhealthy 并卡住 frontend。改用镜像里已有的 `curl -fsS http://127.0.0.1:8080/api/v1/health`，冷启动实测 49.3s，故 `start_period: 90s`。
- **`frontend/Dockerfile.runtime.dockerignore` 不能少**：`frontend/.dockerignore` 第 2 行排除了 `dist`，BuildKit 会把它套到 `Dockerfile.runtime` 上，报 `failed to compute cache key: "/dist": not found`。
- **`INGEST_STAGE_DELAY_MS` 要给到 python-ai**：这个变量只被 `server-ai/app/config.py` 读取，Java 不读；只给 java-backend 时 J4 的五阶段用例只看到 `parsing` 与 `done`。
- **`SPRING_PROFILES_ACTIVE=gate-probe`**：不设则 `GateProbeController` 不注册，J1 十条错误码用例全 404。
- **Windows 系统代理**：`httpx` 会读 `HKCU\...\Internet Settings` 的 `ProxyServer=127.0.0.1:7890`（`ProxyOverride` 里的 `127.*` 对 httpx 不生效），未设 `NO_PROXY=127.0.0.1,localhost` 时 pytest 打 `127.0.0.1:8080` 会拿到 502。
- **容器内构建靠 `maven` 基础镜像，网络波动就会整段失败**：`server-java/Dockerfile:7` 的 `RUN mvn -q -DskipTests package` 首次曾报 `DependencyResolutionException`，隔一会儿重试即成功（同一份 Dockerfile、同一台机器）。依赖层一旦进了 BuildKit 缓存，后续 `--build` 只重跑变更层。日常用 `--mode prebuilt` 绕开这一步。

#### 路线 A 之三：接上真 RAG（Milvus + 智谱 embedding，2026-11-07 实测通过）

上面两条路线跑的是 `AI_PROVIDER=mock`，检索走内存向量库。要验真实链路（切分 → 智谱 `embedding-3` 2048 维 → Milvus → top-k 引用），先把 Milvus 起来，再把 provider 指过去。

```powershell
# 1) 拉镜像（Docker Hub 直连不稳时用镜像站；脚本纯 ASCII，可重复跑）
powershell -ExecutionPolicy Bypass -File tools\pull_milvus.ps1 -SkipExisting

# 2) 起 Milvus（etcd + minio + milvus + attu，网络 xiaoyi-net）
docker compose -f deploy/milvus/docker-compose.yml up -d
Invoke-WebRequest http://127.0.0.1:9091/healthz        # 期望 200 OK

# 3) 填 provider（deploy/local-mysql.env，已被 .gitignore 忽略）
#    AI_PROVIDER=real
#    EMBEDDING_ENDPOINT=https://open.bigmodel.cn/api/paas/v4   # 程序自己拼 /embeddings
#    EMBEDDING_MODEL=embedding-3
#    EMBEDDING_API_KEY=<你的 key>
#    LLM_ENDPOINT=https://open.bigmodel.cn/api/paas/v4
#    LLM_MODEL=glm-4-flash
#    LLM_API_KEY=<同一个 key>
#    MILVUS_URI=http://milvus:19530
#    MILVUS_COLLECTION=xiaoyi_chunks

# 4) 重建 python-ai（要装 pymilvus）并起栈
python tools\docker_deploy.py up --smoke

# 5) 验真实检索：上传 → 建库 → 提问，回答里必须带 [1] 这类引用
```

要点：

- **`deploy/milvus/user.yaml` 里是真实 API key**，已被 `.gitignore:60` 忽略；模板是 `user.yaml.example`，只放占位串。
- **`user.yaml` 只在用 Milvus 内置 Function 时才需要**：本项目默认在 Python 侧调 embedding（`server-ai/app/core/rag/embedder.py`），把 `user.yaml` 摘掉也不影响 A2 的检索链路。启用 Function 有两个实测坑：`textEmbedding.providers.openai.url` 必须写到 `/v4/embeddings`（Milvus 不自动补后缀，写 `/v4` 会 404），Function 的 `params` 里模型名的键是 `model_name` 而不是 `model`（写错智谱回 `1214 model:model cannot be empty`）。两者都写进 `user.yaml.example` 的注释了。
- **minio 需要 `user: "0"`**：`dockerproxy.net/bitnamilegacy/minio` 默认 uid=1001，写卷报 `file access denied, drive may be faulty`，容器恒 unhealthy。
- **Milvus 写后不 flush 就必须用 Strong 一致性读**：`flush()` 实测 8–11 秒，建库路径上会撞穿 J4 的 15s 轮询阈值；改成写侧不 flush + 读侧 `consistency_level="Strong"`（0.05s 就能看到），单份资料建库从 19s 降到 6.1s。代价是换 Milvus 版本要重验这条假设。
- **`/index/status` 的 `embeddingModel` 以 Python manifest 为准**：Java 的 `INDEX_EMBEDDING_MODEL` 只是登记值，真正做向量化的是 Python。两者不一致时顶层字段与 manifest 会自相矛盾（曾出现 `mock-embedding` vs `embedding-3`）。
- **分块仍是 180/30**：`IndexServiceImpl.status()` 在 `manifest.chunkSize` 与任务值不一致时强制 `needs_rebuild`，J4 也有五处断言钉死 180，所以没按 §14.1 改 500/75。

#### 路线 A 之四：混合检索（A3，2026-11-08 实测通过）

A3 默认就开着（`RETRIEVAL_MODE=hybrid`），真 RAG 起来之后无需额外步骤。要对比四档效果：

```powershell
# 四档对照（dense / bm25 / rrf / hybrid），真实 embedding，输出 hit@k / top-1 / MRR
python tools\a3_compare.py --json test-artifacts\a3-compare-real.json

# 接真重排服务再跑一遍
$env:RERANK_ENDPOINT='https://open.bigmodel.cn/api/paas/v4/rerank'; $env:RERANK_MODEL='rerank'
python tools\a3_compare.py --json test-artifacts\a3-compare-rerank.json

# 汇总成报告
python tools\write_a3_report.py
```

要点：

- **降级路径必须保序**：`LexicalReranker` 只做并列消歧，不改写融合分。曾按词面覆盖率重排，top-1 从 5/6 掉到 3/6；0.6/0.4 与 0.85/0.15 加权都只有 4/6，都不如不重排。
- **`HttpReranker` 以服务返回的数组顺序为准**，不按分数二次排序 —— 分数饱和时二次排序等于用 chunk_id 字典序覆盖服务判断。
- **智谱 rerank 分数饱和**：20 候选极差 < 1e-5，加极差 < 0.01 的饱和检测后自动退回保序融合，`diagnostics.degradeReason` 里会写「饱和」。
- **`diagnostics` 不进 HTTP 响应**：`InternalRetrieveResult` 是 `additionalProperties: false`，四路候选只在进程内与报告里可见。
- **跑根门禁前清干净 provider 环境变量**：J6/J7/A1/A2/A3 在进程内装配 app，会继承 shell 环境；带着 `AI_PROVIDER=real` + `MILVUS_URI=http://milvus:19530` 会让它们假失败（实测 112 errors）。要清 `AI_PROVIDER`/`MILVUS_*`/`EMBEDDING_*`/`LLM_*`/`RETRIEVAL_*`/`RERANK_*` 共 20 个键。
- **一个用户同时最多 99 份资料**：`chunk_id` 形如 `D01-C001`，文档号只有两位。新资料取「最小空闲号」，所以删掉的资料腾出的号会被复用；真满了会明确报「已达上限」而不是悄悄把编号压成 99 撞主键（旧实现踩过，Milvus 只回一句 `code=1100`）。对账只回收「早于本次任务开始」的行，不重排编号——重排会改到并发任务正在用的号。

A2 的完整验收数字见 [06_后端施工单.md](03-架构评审/06_后端施工单.md) §10 与 `docs/03-架构评审/evidence/backend-gate-A2.json`；A3 的见 §11 与 `docs/03-架构评审/evidence/backend-gate-A3.json`。

### 路线 B：我要答辩，得能解释代码
```
02-重构设计/RAG文档.md §4-§5      → 先有全局：离线管线怎么建、在线 7 步怎么答
        ↓
02_重构设计/后端文档.md §3        → 「Java 怎么编排、怎么降级、怎么落库」
        ↓
99-v1归档/03-后端设计/B03_建库与检索链路.md → 「改造前怎么切、怎么挑最相关片段」
        ↓
frontend/src/features/chat/ + frontend/src/api/ → 「界面怎么和接口对上」
```

指导书「代码理解」要求的三问，答案分别落在 `RAG文档.md` §4/§5（切分与检索、消息组成）、`frontend/src/features/`（前端表现），v1 对照见 `99-v1归档/` 的 B03/B04。

### 路线 C：我要改成自己的项目

```
02-技术栈/T00 → T02               → 先把依赖和版本摸清
        ↓
02-重构设计/00_项目架构规格.md §7 → 契约不能随便改
        ↓
02-重构设计/04_后端开发提示词.md  → 按 J0→J6/A1→A3 顺序施工
        ↓
frontend/src/api/modules/*.ts     → 前端跟着契约改
```

## 四、任务 ↔ 功能 ↔ 文档映射

> 「后端实现」列的 B 编号均属已归档的 v1 文档，只作历史对照；现行后端实现见 `02-重构设计/后端文档.md` 与 `RAG文档.md` 对应章节。

| 任务（分值） | 功能 | 功能规格 | v1 后端（归档） | 前端实现（现行） | 联调验证 |
| --- | --- | --- | --- | --- | --- |
| 任务1 资料与知识库（20） | F1 F2 F3 | F01 / F02 / F03 | B02 / B03 | `features/knowledge/` | F02 验收 + `regress` 场景 01–02 |
| 任务2 带来源的问答（25） | F4 F5 | F04 / F05 | B04 | `features/chat/` | F05 + `regress` 场景 03–04 |
| 任务3 对照与可信度（20） | F6 F11 | F06 / F11 | B04 / B06 | `features/chat/`（ComparePane） | F06 + `regress` 场景 06 |
| 任务4 检索数量与过程（15） | F7 F8 | F07 / F08 | B03 | `features/chat/`（RetrievalTrace） | F07/F08 + `regress` 场景 05 |
| 任务5 批量对照测试（10） | F9 | F09 | B05 / B07 | `features/eval/`（BatchRunner） | F09 + `regress` 场景 07 |
| 拓展A 清空对话（+5） | F10 | F10 | B01（session） | `features/chat/`（ClearChatButton） | F10 + `regress` 场景 10 |
| 拓展B 片段浏览（+5） | — | F02 §拓展B | B05（`/api/chunks`） | `features/knowledge/`（ChunksView） | F02 拓展B + `regress` 场景 09 |
| 实验报告（10） | — | 验收清单 | — | — | 验收清单 |

## 五、当前实现状态（实测）

| 项 | 实测结果 |
| --- | --- |
| 前端文件 | **84 个** ts/vue/css（`frontend/src`）+ 26 个 spec |
| API 契约 | v2 **29 条对外 + 8 条内部**（`02-重构设计/00_项目架构规格.md` §7.3/§7.4）；v1 的 24 条见归档 B05 |
| 建库（180/30） | **15 片段**（01=2 02=2 03=2 04=3 05=3 06=3）——v1 实测值；v2 实测 6 篇语料 = 16 片段（含标题继承后的边界差异） |
| 前端测试 | **316/316 通过**（26 个 spec） |
| 前端门禁 | **10 份阶段报告全 pass**（P1→P6，含 build） |
| 批量对照 | 查资料 **10/10** · 不查资料 **1/10**（v1 mock 数据） |
| 浏览器实测 | 冒烟 7 项 + CDP 回归 10 场景全 PASS，**21 张截图** |
| 构建产物 | `vendor-ui 798 kB (gzip 252)` + `vendor 189 (68)` + `vendor-vue 114 (44)` + 各页面 chunk |
| 后端 v1 | **已删除**（14 文件 / 1921 行），归档 `.snapshots/_archive/v1-backend-removed-20261101` |
| 后端 v2（Java） | **H1–H4 + P0–P8 + A2/A3 + N1–N6 已完成**：`server-java/` Spring Boot 3.2.10 / Java 21、115 个主类 / 11194 行、15 张表 Flyway V1–V9、29 条对外路由统一信封、会话/消息/资料真落库、SSE 五类事件 + 检索轨迹、串行建库 + `@Scheduled` 五阶段推进、上传口 99 份前置拦截。`mvn verify` **88 passed** |
| 后端 v2（Python） | **A1 + A2 + A3 + N1–N3 + N5 + N6 已完成**：`server-ai/` 27 个文件 / 3677 行，含切分（标题继承 + 边界回退）、嵌入（OpenAI 兼容 + 分批重试）、向量库（Milvus / 内存双实现）、检索管线、BM25 倒排 + RRF 融合 + 可降级重排 + 查询改写（N6 真实 provider 端到端取证）、防幻觉提示、流式 provider、追问推荐、全局摘要卡、结构化输出约束。`test/A1-ai-skeleton` **24 passed**、`test/A2-rag` **37 passed**、`test/A3-hybrid` **31 passed** |
| 真实 RAG 链路 | 智谱 `embedding-3`（2048 维）+ Milvus 3.0.0：建库 8 片段、top-3 引用、跨用户 0 命中、SSE 回答带 `[1]` 标注，探针 PASS（`docs/03-架构评审/evidence/backend-gate-A2.json`） |
| 混合检索（A3） | 容器栈 `RETRIEVAL_MODE=hybrid`：SSE 阶段序列 `rewriting → retrieving → reranking → generating`，3 条引用全部 `stage=rerank`，跨用户 0 条（`docs/03-架构评审/evidence/backend-gate-A3.json`）。四档对照 6 问 6 语料 k=3：`dense` top-1 6/6 MRR 1.0000、`bm25` 3/6 0.7222、`rrf` 5/6 0.9167、`hybrid` 5/6 0.9167 —— **本批语料上 dense 已满分，混合检索没超过它**，价值在向量质量不稳时仍能到 5/6 |
| 参数实验（E3 / N1） | 四根轴从装饰变成真执行：每组先按本组 `chunkSize`/`overlap` 重建索引再评测、跑完恢复 180/30、实验期间 `POST /index/rebuild` 回 40902、组数上限 8、`metrics.effective` 如实标 `summary=false`。`test/J5-eval` **29 passed**、`test/A3-hybrid` **29 passed**、Java **71 passed**、前端 **309 passed**（`docs/03-架构评审/evidence/backend-gate-N1.json`） |
| 追问推荐（B1 / N2） | 从硬编码一句变成真生成 + 落库回放：`done.suggestions` 1–3 条随问题变化、刷新后 `GET /messages` 仍带 chips、direct 模式给空数组、生成失败（超时/异常/脏 JSON）一律降级不抛。`test/A1-ai-skeleton` **24 passed**、`test/J3-sse` **38 passed**、Java **74 passed**、前端 **310 passed**（`docs/03-架构评审/evidence/backend-gate-N2.json`） |
| 全局摘要卡（A5 / N3） | 建库的 `summarizing` 从空转变成真产出：`D00-C001` 统计卡（全库共 N 份资料）+ `D00-C002` 规则卡（借阅条款），`doc_id` 用哨兵 `__summary__`；只在全局问题（一共/总共/资料库/汇总…）时兜底替换末位，具体问题不塞卡；`gen_summary=false` 跳过生成、生成失败降级为空且任务仍 SUCCEEDED。`test/A2-rag` **32 passed**（新增 11 条）、`test/J4-ingest` **30 passed**、Java **76 passed**、前端 **310 passed**（`docs/03-架构评审/evidence/backend-gate-N3.json`） |
| 反馈闭环（C1 / N4） | 候选池从只进不出变成能进实验：`eval_candidate` 加 `keywords`（V9），采纳时可补判分关键词，**补了就计分、没补就标 `unscored` 不进分母**；实验选题支持 `C<候选id>` 与题库题号混选（pending/ignored/别人的一律 40001，与题号写错同一条消息）；`GET /eval/candidates/export` 回真 `text/csv`（BOM + `question,keywords` + 引号转义，只含 accepted）。`test/J5-eval` **41 passed**（新增 12 条）、Java **84 passed**、前端 **311 passed**（`docs/03-架构评审/evidence/backend-gate-N4.json`） |
| 结构化回答（B3 / N5） | `SYSTEM_PROMPT` 追加第 6 条（前五条一字未改）：对比/枚举/分步骤时用 markdown 表格或有序列表，`[n]` 写在单元格或列表项内，禁 HTML 与图片。后端与前端零改动——`markdown.ts` 的白名单渲染早已就位，缺的一直是「模型不知道要输出结构化内容」。`test/A2-rag` **37 passed**（新增 5 条，含「规则真的进了 `build_messages`」）、前端 **316 passed**（新增 `structured-answer.spec.ts` 5 条）、Java **84 passed**（`docs/03-架构评审/evidence/backend-gate-N5.json`） |
| 收口（N6） | 两件遗留补齐：①**99 份上限前移到上传口** —— `DocumentServiceImpl.upload()` 第一行 `requireCapacity`，用 `countByUploadedByAndDeletedFalse` 统计（软删不占名额），`existing + files.size() > 99` 回 400+40001，文案直接说清「同时最多 99 份」；原本要传完、点建库、等几秒才看到「编号不够用」。②**查询改写端到端取证** —— 真实 provider（embedding-3 / glm-4-flash）下「那借期呢？」→「普通图书的借期是多久？」，两轮 top3 都命中 `02_借阅规则.md`；两条 live 用例在 mock 档 skip，另有 `test_mock_provider_skips_rewrite_by_design` 钉住「skip 的理由是真的」。`test/J2-crud` **35 passed**（新增 5 条）、`test/A3-hybrid` **31 passed**、Java **88 passed**、两档根门禁 `partial=false` 覆盖 11/11 阶段（`docs/03-架构评审/evidence/backend-gate-N6.json`） |
| 根门禁 | 真实档 `J0 J1 J2 J4 J6 J7 A1 A2 A3` **343 passed / 3 skipped**，9 阶段合计 208.35s；mock 档 `J3 J5` **79 passed**，合计 96.15s。两轮由 `test/run_all.py` 合并成一份 `backend-gate-all.json`，覆盖 11/11 阶段（`partial=false`、`providerProfiles=[mock,real]`），每条 gate 带 `ranAt` 标明属于哪一轮。3 个 skip 是 J1 的 host 占位 1 条 + A3 的 live 改写 2 条，均在阶段备注写明原因 |

## 六、目录与文件对照（代码在哪）

```
D:\VM1\Xiaoyi_RAG_bookstore\
├─ frontend\       前端（Vue 3 + Vite + TypeScript，P1–P6 全部完成）
│  ├─ src\         main.ts / App.vue / app（布局+路由）/ api / features / stores / utils / styles
│  ├─ test\        26 个 vitest spec（316 项）
│  ├─ scripts\     gate.mjs（四道门禁）/ smoke.mjs / regress.mjs（CDP 10 场景）/ snapshot.mjs / cdp.mjs
│  ├─ dist\        Vite 构建产物（Java 网关或 nginx 托管这个目录）
│  └─ README.md    启动方式、mock 与真实后端切换、三条硬约束
├─ assets\         数据资产（v2 唯一源）
│  ├─ data\        6 份教学资料 .md（01–06，06 未核实）
│  └─ eval\        questions.csv（13 道测试题 T01–T13）+ keywords.csv（判分关键词）
├─ docs\           本文档体系（含 `api/` 四份契约）
├─ server-java\    Java 网关（Spring Boot 3.2.10 / Java 21，J0–J4 + N1–N6 已完成）
├─ test\           后端门禁测试（pytest，J0→A3 十阶段）
├─ .snapshots\     阶段快照与已删资产的归档（web/、v1 前端文档、v1 后端源码，不进版本库）
└─ .gitattributes  .gitignore
```

> v1 的 `app\`、`cli\`、`tools\`、`run.cmd`、`index.json`、`config.json`、`logs\`、`exports\` 已删除。
> 仓库根的 `data\`、`eval\`、`questions.csv` 已迁入 `assets\`（逐字节同一份，`git cat-file blob HEAD:<old>` 可回溯），不再保留双份。
> `server-ai\`（Python RAG 服务）已按手册 A1 阶段建成：A1 骨架 + A2 检索 + A3 混合检索 + N1 options + N2 追问推荐 + N3 摘要卡 + N5 结构化输出约束 + N6 改写端到端取证，27 个文件 / 3677 行。

## 七、关键约定（改代码前必读）

1. **Key 永不落盘**：只存进程内存或环境变量；`config.json` 的白名单里没有 key 字段（v1 约定，v2 沿用为「配置走环境变量」）。
2. **`questions.csv` 不放 `data/`**：它是测试集，放进 `data/` 会被当成资料切块。现位置 `assets/eval/questions.csv`，语料在 `assets/data/`。
3. **编码统一 UTF-8**：`.py/.md/.json/.ts/.vue` 无 BOM + LF；`questions.csv` / `keywords.csv` / 导出 CSV 带 BOM（Excel 需要）。
   ⚠️ 不要用 PowerShell `Set-Content -Encoding utf8` 写文件（会加 BOM，Vite 读 `package.json` 直接报错）。
4. **索引原子写**：v1 是 `index.json` 先写同目录临时文件再 `replace`；v2 由 Milvus Lite + MySQL 事务承担。
5. **契约唯一源头**：`docs/api/openapi-public.yaml` 与 `openapi-internal.yaml` → 三端各自生成类型，禁止手改漂移。
6. **改了资料或分块参数必须重建索引**；前端常量 `CHUNK_SIZE_DEFAULT=180` / `OVERLAP_DEFAULT=30` 只作表单默认值，**以 manifest 实际值为准**。
7. **mock 档是默认档**：v2 的 `mock provider` 是联调契约的一部分；mock 通过不代表真实 RAG 检索质量已验收，A2/A3 单独验收。
8. **真实启动必须注入密钥**：`AUTH_JWT_SECRET` 至少 32 个 UTF-8 字节，`INTERNAL_TOKEN` 必须显式设置；示例生成：`openssl rand -base64 48`、`openssl rand -hex 32`。Compose 缺少任一密钥时应在配置阶段失败。
