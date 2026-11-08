# 门禁报告归档

> 本目录由 `tools/archive_evidence.py` 生成，**不要手工编辑**。
> 源目录 `test-artifacts/` 被 `.gitignore` 忽略（内含 147 MB 依赖与数百 MB storage），
> 这里只留小体积、可公开的 JSON，让文档里的数字可被核对。

重新生成：

```powershell
python tools\write_a3_report.py     # 或对应阶段自己的报告工具
python tools\archive_evidence.py
```

## 清洗规则

归档前只做两件事，其余内容原样保留：

1. **本机绝对路径占位** —— `D:\VM1\Xiaoyi_RAG_bookstore` → `<repo>`、`D:\python` → `<python>`、`C:\Users\limingjie` → `<home>`、`D:\IDEA` → `<idea>`、`D:\MYSQL` → `<mysql>`。
2. **剥掉 docker inspect 的无用 label** —— `com.docker.compose.config-hash`、`com.docker.compose.image`（镜像 digest）、`org.opencontainers.image.description`（整段镜像宣传语）、`maintainer`、`desktop.docker.io/binds/0/Source`。这些换次构建就变，留着只会让一行 JSON 膨胀到 1500 字节。`service` / `project` / `version` / `depends_on` / `ports` 保留 —— 它们才是「这个容器属于哪套 compose」的证据。

## 关于 `backend-gate-all.json`

这份报告由 `test/run_all.py` 写出。J3/J5 断言的是 mock provider 的确定性输出，必须 `AI_MOCK=true`；其余阶段要真实链路，必须 `AI_MOCK=false`。两档互斥，**单次调用跑不出全量**，所以 `run_all.py` 默认把多轮结果合并进同一份文件，每条 gate 带 `ranAt` 标明属于哪一轮。`partial: true` 表示还有阶段没被任何一轮覆盖，此时索引的结论列会标注「仅 X/Y，非全量」。

## 归档清单

| 文件 | 大小 | 结论 | 内容 SHA256 前 16 位 |
| --- | ---: | --- | --- |
| `a3-compare-real.json` | 14,488 B | 6 题 · dense MRR 1.0 / hybrid MRR 0.9167 | `98b2a3d4aa45b960` |
| `a3-compare-rerank.json` | 14,476 B | 6 题 · dense MRR 1.0 / hybrid MRR 0.9167 | `0d0916fc673ec5c0` |
| `backend-gate-A2.json` | 5,815 B | pass · 6 个门禁 | `fa21a83a97a53b3c` |
| `backend-gate-A3.json` | 6,918 B | pass · 3 个门禁 | `7f11d6f4e8c8e668` |
| `backend-gate-all.json` | 2,975 B | pass · 11 个门禁 | `74c8696b4f5e7c82` |
| `backend-gate-H0.json` | 759 B | pass · 3 个门禁 | `72cd6fbdbbb51a0a` |
| `backend-gate-H1.json` | 538 B | pass · 3 个门禁 | `a9b9745f584c1769` |
| `backend-gate-H2.json` | 737 B | pass · 4 个门禁 | `9e11b263b6cf866d` |
| `backend-gate-H3.json` | 555 B | pass · 3 个门禁 | `d06ccc27af6e4a9c` |
| `backend-gate-H4.json` | 1,030 B | pass · 5 个门禁 | `1a7eff3d57445b0b` |
| `backend-gate-J0.json` | 470 B | pass · 3 个门禁 | `e1b19cf8cf60c025` |
| `backend-gate-J1.json` | 851 B | pass · 4 个门禁 | `757e4320b740f5f9` |
| `backend-gate-J2.json` | 1,677 B | pass · 4 个门禁 | `d3109a1cbadaf7c6` |
| `backend-gate-J3.json` | 2,134 B | pass · 7 个门禁 | `41068a23087e2140` |
| `backend-gate-J4.json` | 2,462 B | pass · 5 个门禁 | `7fe65e3654848d5b` |
| `backend-gate-N1.json` | 7,215 B | pass · 5 个门禁 | `eb5f555349bdb17a` |
| `backend-gate-P7.json` | 13,732 B | pass | `a987df2de772c69a` |
| `backend-gate-P8.json` | 11,228 B | pass · 10 个门禁 | `957575d0ecfda8af` |
| `compose-smoke.json` | 514 B | pass | `e7aea915f0a82dc6` |
| `docker-deploy-full.json` | 5,517 B | pass | `7c36df626752c251` |
| `docker-deploy-prebuilt.json` | 1,203 B | pass | `564547537612c17c` |
| `docker-deploy-stack.json` | 6,656 B | pass | `297ac5c3ff9512e3` |
| `local-mysql-verify.json` | 1,755 B | pass | `d52b72c3fb0a5e6e` |
| `p7-browser.json` | 2,601 B | 4/4 项 ok | `af8e57225bf4a525` |
| `p7-evidence.json` | 1,551 B | 3/3 项 ok | `e53deb4a82cd2768` |

## 未归档的文件

| 文件 | 原因 |
| --- | --- |
| `p7-env.json` | 含 `AUTH_JWT_SECRET`、`INTERNAL_TOKEN` 与两个 bootstrap 口令 |
| `local-mysql-public.json` | 含两个 bootstrap 口令 |
| `p7-pids.json` | 本机进程号，换机器即失效 |
| `_pm/`、`*-storage/`、`screenshots/` | 依赖与二进制产物，体积过大 |

## 校验

`--check` 会比对源目录与归档目录的哈希；源报告重跑后没重新归档时会报出来：

```powershell
python tools\archive_evidence.py --check
```
