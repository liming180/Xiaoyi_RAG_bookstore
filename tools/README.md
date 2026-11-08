# tools/ 脚本索引

这里的脚本只服务「本机跑通 + 取证」，不进运行时。产品代码在 `server-java/`、`server-ai/`、`frontend/`。

## 日常用（按场景选一条）

| 脚本 | 用途 |
| --- | --- |
| `docker_deploy.py` | **容器栈统一入口**。`up|status|logs|down|build|push`，`--mode prebuilt|full|stack`（默认 prebuilt），`--smoke` 跑冒烟，`--prepare-db` 建库+建容器账号，`--push --registry R --tag T` 推镜像。报告落 `test-artifacts/docker-deploy-<mode>.json`。 |
| `local_mysql.py` | **本机进程入口**。`prepare` 建空库 → `up` 起 Python(8000)+Java(8080) 并让 Flyway 建表 → `verify` 双账号+13 表 → `status` / `down` / `drop-db`。读 `deploy/local-mysql.env`。 |
| `local_mysql_smoke.py` | 端到端冒烟：上传 → 建库 → 轮询终态 → 断言 A/B 片段互不可见 → 直连库核对行数。 |
| `compose_smoke.py` | 容器栈冒烟：走 nginx（默认 `http://127.0.0.1:8088`）验首页 / 双账号登录 / 列表隔离 / 建库 / chunks 隔离 / 库核对。`--db-via-container` 改走 `compose exec mysql`（`stack` 模式用）。报告落 `test-artifacts/compose-smoke.json`。 |
| `check_stack_db.py` | 查 `deploy/docker-compose.yml` 里 mysql 容器的表数 / Flyway 历史 / 文档与片段归属，用来核对「空库起栈后 Flyway 是否真建了 13 张表」。 |
| `local_mysql_grant_container.py` | 建 `xiaoyi@'%'` 账号并只授 `xiaoyi_rag_local_gate.*`。容器连宿主机库前跑一次。 |
| `pull_milvus.ps1` | 拉 Milvus 四件套（etcd / minio / milvus / attu），每个镜像按多个镜像站依次重试，`-SkipExisting` 跳过已有。**必须纯 ASCII**：Windows PowerShell 5.1 用 ANSI 代码页读 `.ps1`，中文注释会让脚本解析失败。 |
| `arch_snapshot.py` | 生成 `docs/03-架构评审/snapshot/架构快照.md`（文件数、行数、类数）。 |
| `a3_compare.py` | **四档检索对照**（dense / bm25 / rrf / hybrid）。进程内 app + 真实或 mock provider，输出 hit@k / top-1 / MRR / 耗时与逐题 top-3，`--json` 落盘。看真实效果要先把 `AI_PROVIDER=real` 与 `EMBEDDING_*` 放进环境；接 `RERANK_ENDPOINT` 才走真重排。 |
| `write_a3_report.py` | 跑 A3 套件 + 回归 + `mvn verify`，汇总两份对照 JSON，生成 `test-artifacts/backend-gate-A3.json`。`--skip-suites` 只汇总已有产物。 |
| `a3_stack_probe.py` | **容器栈 A3 端到端探针**：打 8080 上的真实部署（登录 → 上传 → 建库 → SSE → 轨迹），验 `RETRIEVAL_MODE=hybrid` 下阶段序列含 `rewriting`/`reranking`、引用 `stage=rerank`、跨用户 0 条。与 `a3_compare.py` 互补：一个验指标，一个验部署形态。 |
| `archive_evidence.py` | 把 `test-artifacts/` 里的小体积报告归档到 `docs/03-架构评审/evidence/` 并重建 `index.md`（大小、结论、SHA256）。排除含凭据的 `p7-env.json` / `local-mysql-public.json` 与含进程号的 `p7-pids.json`，并把本机绝对路径替换成 `<repo>` / `<python>` / `<home>` 占位。`--check` 比对源与归档是否一致。 |

## 环境装配（被上面几个 import，不单独跑）

| 脚本 | 用途 |
| --- | --- |
| `p7_env.py` | 读/写 `test-artifacts/p7-env.json`；进程内环境变量优先于 json。 |
| `p7_up.py` | 装配 env、起 uvicorn / java / web、按 pid 收进程。`build_env()` 是唯一的环境拼装点。 |
| `p7_java_fg.py` | 前台起 java（日志进 `test-artifacts/p7-java-fg.log`）。`main(env=None)` 传 env 时不读 json。 |
| `local_ai_up.py` | 前台起 uvicorn（`cwd=server-ai`，注入 `INTERNAL_TOKEN` 与 `STORAGE_ROOT`）。 |
| `p7_pytest.py` | 带 P7 环境跑 pytest 的包装。 |
| `local_mysql_web.mjs` | 起前端静态服务给浏览器验收用。 |
| `pull_images.ps1` | 按镜像逐个重试拉取。**必须保持纯 ASCII**：Windows PowerShell 5.1 用 ANSI 代码页读 `.ps1`，中文注释会把字符串截断成 `Array index expression is missing or not valid`。 |

## 一次性（已完成使命，留作记录）

| 脚本 | 做了什么 |
| --- | --- |
| `p7_acceptance.py` | P7 的 C/D/F 三项取证（B 项由 `test/J7-isolation` 覆盖）。 |
| `update_p7_compose.py` / `update_p8_compose.py` | 把容器栈实测数字写回 `test-artifacts/backend-gate-P7.json` / `-P8.json`。 |
| `update_p7_stack.py` | 把 `--mode stack`（mysql 容器）的实测证据追加进 P7 报告 A 项。 |
| `update_p8_stack.py` | 把三种 compose 形态的实测结果写回 P8 报告的 compose-stack 门禁，并刷新 knownLimitations。 |
| `update_p8_push.py` | 把镜像推送 + 远端 digest 校验的实测结果写回 P8 报告的 image-push 门禁。 |
| `normalize_p7_report.py` | 把 P7 报告 A 项的 `verifiedInstead` / `equivalentEvidence` 收敛为 `evidence`。 |
| `refresh_p7_evidence.py` | 用最近一次 `compose-smoke.json` 刷新 P7 A 项的冒烟数字。 |
| `fix_internal_openapi.py` | 修正 `docs/api/openapi-internal.yaml` 里 `InternalParseRequest` 的字段缩进。 |
| `p7_diag_tasks.py` | 打印门禁库最近的 `index_task` / `document` 行，排查建库卡住。 |
| `p7_java_probe.py` | 起 java 后捕获退出码与日志尾部。 |
| `write_a2_report.py` | 把 A2 的实测数字写成 `test-artifacts/backend-gate-A2.json`（6 个门禁 + 修复清单 + 未采纳项）。 |

## 约定

- 库名必须以 `_gate` / `_test` 结尾，`local_mysql.py` 会拒绝其它名字 —— `test/conftest.py` 的 `clean_db` 会 `DELETE FROM` 十张表，指错库就当场清掉开发数据。
- `AUTH_JWT_SECRET` ≥ 32 UTF-8 字节、`INTERNAL_TOKEN` 非空、bootstrap 口令 12–72 字节，缺一项 `prepare` 就退出。
- 表结构只有一处来源：`server-java/src/main/resources/db/migration/V1–V7`。不要手工 `source` 迁移 SQL，Flyway 的校验和会对不上。
- 跑 pytest 前设 `NO_PROXY=127.0.0.1,localhost`：Windows 系统代理（`HKCU\...\Internet Settings` 的 `ProxyServer=127.0.0.1:7890`）会被 httpx 读取，`ProxyOverride` 里的 `127.*` 对 httpx 不生效。
