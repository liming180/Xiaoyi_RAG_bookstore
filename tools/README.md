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
| `arch_snapshot.py` | 生成 `docs/03-架构评审/snapshot/架构快照.md`（文件数、行数、类数）。 |

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

## 约定

- 库名必须以 `_gate` / `_test` 结尾，`local_mysql.py` 会拒绝其它名字 —— `test/conftest.py` 的 `clean_db` 会 `DELETE FROM` 十张表，指错库就当场清掉开发数据。
- `AUTH_JWT_SECRET` ≥ 32 UTF-8 字节、`INTERNAL_TOKEN` 非空、bootstrap 口令 12–72 字节，缺一项 `prepare` 就退出。
- 表结构只有一处来源：`server-java/src/main/resources/db/migration/V1–V7`。不要手工 `source` 迁移 SQL，Flyway 的校验和会对不上。
- 跑 pytest 前设 `NO_PROXY=127.0.0.1,localhost`：Windows 系统代理（`HKCU\...\Internet Settings` 的 `ProxyServer=127.0.0.1:7890`）会被 httpx 读取，`ProxyOverride` 里的 `127.*` 对 httpx 不生效。
