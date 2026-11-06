#!/usr/bin/env python3
"""架构快照生成器 — 把代码库压成 LLM 能一次读完的事实清单。

设计原则:
  1. 只输出「事实」，不做「评价」。评价交给 LLM，事实交给机器。
  2. 全部确定性：同一份代码跑两次结果一致，便于 diff 追踪架构漂移。
  3. 零依赖：只用标准库，任何机器 `python tools/arch_snapshot.py` 直接跑。

用法:
    python tools/arch_snapshot.py
    python tools/arch_snapshot.py --out docs/03-架构评审/snapshot/架构快照.md
    python tools/arch_snapshot.py --god-lines 400
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    "node_modules", ".git", "target", "dist", "build", "__pycache__",
    ".snapshots", "test-artifacts", ".venv", "venv", ".idea", ".vscode",
    "storage", "coverage", ".pytest_cache", ".mypy_cache",
}

CODE_EXT = {
    ".java": "Java", ".py": "Python", ".ts": "TypeScript", ".vue": "Vue",
    ".js": "JavaScript", ".mjs": "JavaScript", ".sql": "SQL", ".css": "CSS",
}


# ---------------------------------------------------------------- 基础工具

def iter_files(base: Path, exts: set[str] | None = None):
    """遍历目录下源码文件，跳过依赖/产物目录。"""
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if exts and p.suffix not in exts:
                continue
            yield p


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


# ---------------------------------------------------------------- 采集

def collect_scale() -> dict:
    """三端规模：文件数 / 代码行数。"""
    ends = {"server-java": ROOT / "server-java", "server-ai": ROOT / "server-ai",
            "frontend": ROOT / "frontend" / "src", "test": ROOT / "test"}
    out = {}
    for name, base in ends.items():
        if not base.exists():
            out[name] = {"files": 0, "lines": 0, "by_lang": {}}
            continue
        by_lang: Counter = Counter()
        files = lines = 0
        for p in iter_files(base, set(CODE_EXT)):
            if "node_modules" in p.parts:
                continue
            by_lang[CODE_EXT[p.suffix]] += 1
            files += 1
            lines += count_lines(p)
        out[name] = {"files": files, "lines": lines, "by_lang": dict(by_lang)}
    return out


def collect_god_files(threshold: int) -> list[tuple[str, int]]:
    """超长文件 —— 上帝模块的机械证据。"""
    rows = []
    for base in (ROOT / "server-java" / "src", ROOT / "server-ai" / "app", ROOT / "frontend" / "src"):
        if not base.exists():
            continue
        for p in iter_files(base, set(CODE_EXT)):
            n = count_lines(p)
            if n >= threshold:
                rows.append((rel(p), n))
    return sorted(rows, key=lambda r: -r[1])


def collect_java_layers() -> dict:
    """Java 分层文件分布 —— 看分层是否落地。"""
    base = ROOT / "server-java" / "src" / "main" / "java"
    if not base.exists():
        return {}
    layers: dict[str, list[str]] = defaultdict(list)
    for p in base.rglob("*.java"):
        parts = p.relative_to(base).parts
        # com/xiaoyi/rag/<layer>/...
        layer = parts[3] if len(parts) > 4 else "(root)"
        layers[layer].append(rel(p))
    return {k: v for k, v in sorted(layers.items())}


JAVA_MAPPING = re.compile(
    r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']*)[\"']?"
)


def collect_java_endpoints() -> list[tuple[str, str, str]]:
    """Java 对外端点：HTTP 方法 / 路径 / 所在类。"""
    base = ROOT / "server-java" / "src" / "main" / "java"
    if not base.exists():
        return []
    rows = []
    for p in base.rglob("*Controller.java"):
        text = read(p)
        cls = re.search(r"@RequestMapping\s*\(\s*[\"']([^\"']*)[\"']", text)
        prefix = cls.group(1) if cls else ""
        for m in JAVA_MAPPING.finditer(text):
            verb, path = m.group(1), m.group(2)
            if verb == "Request":
                continue
            full = (prefix.rstrip("/") + "/" + path.lstrip("/")) if prefix else path
            rows.append((verb.upper(), full, p.stem))
    return sorted(rows, key=lambda r: (r[1], r[0]))


PY_ROUTE = re.compile(r"@app\.(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)[\"']")


def collect_py_routes() -> list[tuple[str, str, str]]:
    """Python 内部端点：HTTP 方法 / 路径 / 所在文件。"""
    base = ROOT / "server-ai" / "app"
    if not base.exists():
        return []
    rows = []
    for p in base.rglob("*.py"):
        for m in PY_ROUTE.finditer(read(p)):
            rows.append((m.group(1).upper(), m.group(2), rel(p)))
    return sorted(rows, key=lambda r: r[1])


def collect_py_import_graph() -> tuple[list[tuple[str, str]], list[list[str]]]:
    """Python 模块 import 图 + 环检测（循环依赖是分层的头号破坏者）。"""
    base = ROOT / "server-ai" / "app"
    if not base.exists():
        return [], []

    def mod_name(p: Path) -> str:
        parts = list(p.relative_to(base).parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][:-3]
        return "app." + ".".join(parts) if parts else "app"

    modules = {mod_name(p): p for p in base.rglob("*.py")}
    graph: dict[str, set[str]] = {m: set() for m in modules}
    edges = []

    for m, p in modules.items():
        try:
            tree = ast.parse(read(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets.append(node.module)
            elif isinstance(node, ast.Import):
                targets.extend(a.name for a in node.names)
            for t in targets:
                if t in modules and t != m:
                    graph[m].add(t)
                    edges.append((m, t))

    # Tarjan SCC
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[list[str]] = []
    counter = [0]

    def strongconnect(v: str):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph[v]:
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                cycles.append(sorted(comp))

    for v in list(graph):
        if v not in index:
            strongconnect(v)

    return edges, cycles


MUTABLE_STATE = re.compile(
    r"^([A-Za-z_]\w*)\s*(?::\s*[^=\n]+)?=\s*(\{\s*\}|\[\s*\]|dict\(\s*\)|list\(\s*\)|set\(\s*\))\s*$"
)


def collect_module_state() -> list[tuple[str, str]]:
    """Python 模块级可变全局状态 —— 多 worker 下数据不共享、测试互相污染。"""
    base = ROOT / "server-ai" / "app"
    if not base.exists():
        return []
    rows = []
    for p in base.rglob("*.py"):
        for line in read(p).splitlines():
            m = MUTABLE_STATE.match(line)
            if m:
                rows.append((rel(p), m.group(1)))
    return rows


def collect_frontend_structure() -> dict:
    """前端 features 切片与 API 模块分布。"""
    base = ROOT / "frontend" / "src"
    if not base.exists():
        return {}
    out: dict[str, dict] = {}
    for group in ("features", "api/modules", "stores", "composables", "components", "app"):
        d = base / group
        if d.exists():
            files = [rel(p) for p in iter_files(d, set(CODE_EXT))]
            out[group] = {"count": len(files), "files": sorted(files)}
    return out


def collect_tests() -> dict:
    """三端测试现状 —— 企业级评审的第一道硬门槛。"""
    out = {}
    java_test = ROOT / "server-java" / "src" / "test"
    java_main = ROOT / "server-java" / "src" / "main"
    out["java_test_files"] = len(list(java_test.rglob("*.java"))) if java_test.exists() else 0
    out["java_main_files"] = len(list(java_main.rglob("*.java"))) if java_main.exists() else 0
    out["java_test_names"] = sorted(p.stem for p in java_test.rglob("*.java")) if java_test.exists() else []

    fe_test = ROOT / "frontend" / "test"
    out["frontend_test_files"] = len(list(fe_test.rglob("*.ts"))) if fe_test.exists() else 0
    out["frontend_spec_files"] = len(list(fe_test.rglob("*.spec.ts"))) if fe_test.exists() else 0

    ai_test = ROOT / "server-ai" / "tests"
    out["ai_test_files"] = len(list(ai_test.rglob("test_*.py"))) if ai_test.exists() else 0

    root_test = ROOT / "test"
    out["root_test_files"] = len(list(root_test.rglob("*.py"))) if root_test.exists() else 0
    return out


def collect_engineering() -> dict:
    """工程化配置清单 —— CI / 容器 / 部署 / 文档。"""
    checks = {
        "CI 流水线 (.github/workflows)": ROOT / ".github" / "workflows",
        "GitLab CI": ROOT / ".gitlab-ci.yml",
        "Java Dockerfile": ROOT / "server-java" / "Dockerfile",
        "AI Dockerfile": ROOT / "server-ai" / "Dockerfile",
        "前端 Dockerfile": ROOT / "frontend" / "Dockerfile",
        "docker-compose": ROOT / "deploy" / "docker-compose.yml",
        "K8s/Helm 清单": ROOT / "deploy" / "k8s",
        "Makefile": ROOT / "Makefile",
        "根 README": ROOT / "README.md",
        "API 契约 (openapi)": ROOT / "docs" / "api" / "openapi-public.yaml",
    }
    return {k: v.exists() for k, v in checks.items()}


DEBT = re.compile(r"\b(TODO|FIXME|HACK|XXX|DEPRECATED)\b")


def collect_debt() -> dict:
    """技术债标记与潜在硬编码密钥。"""
    counts: Counter = Counter()
    samples: list[tuple[str, int, str]] = []
    secrets: list[tuple[str, int, str]] = []
    secret_re = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[\"'][^\"']{3,}[\"']"
    )
    for base in (ROOT / "server-java" / "src", ROOT / "server-ai" / "app", ROOT / "frontend" / "src"):
        if not base.exists():
            continue
        for p in iter_files(base, set(CODE_EXT)):
            for i, line in enumerate(read(p).splitlines(), 1):
                m = DEBT.search(line)
                if m:
                    counts[m.group(1)] += 1
                    if len(samples) < 15:
                        samples.append((rel(p), i, line.strip()[:110]))
                if secret_re.search(line) and "example" not in line.lower():
                    if len(secrets) < 15:
                        secrets.append((rel(p), i, line.strip()[:110]))
    return {"counts": dict(counts), "samples": samples, "secrets": secrets}


def collect_layering_violations() -> list[tuple[str, str, str]]:
    """分层越界 / 反向依赖 —— 企业级分层的核心判据。

    规则:
      Java: controller 直接 import repository（跳过 service）= 越层
      Java: repository / model 反向 import service 或 controller = 倒置
      Python: 非入口模块 import app.main = 反向依赖入口
    """
    rows: list[tuple[str, str, str]] = []

    jbase = ROOT / "server-java" / "src" / "main" / "java"
    if jbase.exists():
        for p in jbase.rglob("*.java"):
            text = read(p)
            layer = p.relative_to(jbase).parts[3] if len(p.relative_to(jbase).parts) > 4 else ""
            if layer == "controller" and ".repository." in text:
                rows.append((rel(p), "controller → repository", "跳过 service 直接访问数据层"))
            if layer in ("repository", "model") and (
                ".service." in text or ".controller." in text
            ):
                rows.append((rel(p), f"{layer} → 上层", "底层反向依赖上层"))

    pbase = ROOT / "server-ai" / "app"
    if pbase.exists():
        for p in pbase.rglob("*.py"):
            if p.name == "main.py":
                continue
            text = read(p)
            if re.search(r"from\s+app\.main\s+import|import\s+app\.main", text):
                rows.append((rel(p), "→ app.main", "业务模块反向依赖入口模块"))

    return rows


def collect_deps() -> dict:
    """三端依赖清单（Java 只取 <dependencies> 块，排除构建插件）。"""
    out = {}
    pom = ROOT / "server-java" / "pom.xml"
    if pom.exists():
        text = read(pom)
        m = re.search(r"<dependencies>(.*?)</dependencies>", text, re.S)
        block = m.group(1) if m else ""
        out["java"] = re.findall(r"<artifactId>([^<]+)</artifactId>", block)
    pkg = ROOT / "frontend" / "package.json"
    if pkg.exists():
        import json
        try:
            d = json.loads(read(pkg))
            out["frontend_deps"] = sorted(d.get("dependencies", {}))
            out["frontend_dev"] = sorted(d.get("devDependencies", {}))
        except json.JSONDecodeError:
            pass
    req = ROOT / "server-ai" / "requirements.txt"
    if req.exists():
        out["python"] = [l.strip() for l in read(req).splitlines() if l.strip() and not l.startswith("#")]
    return out


def collect_sql() -> list[tuple[str, str]]:
    """Flyway 迁移清单 —— 数据模型演进轨迹。"""
    base = ROOT / "server-java" / "src" / "main" / "resources" / "db" / "migration"
    if not base.exists():
        return []
    return [(p.name, f"{count_lines(p)} 行") for p in sorted(base.glob("*.sql"))]


def collect_git() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, timeout=5).stdout.strip()
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, timeout=5).stdout.strip()
        return {"commit": commit or "N/A", "branch": branch or "N/A"}
    except (OSError, subprocess.SubprocessError):
        return {"commit": "N/A", "branch": "N/A"}


# ---------------------------------------------------------------- 渲染

def render(god_lines: int) -> str:
    scale = collect_scale()
    gods = collect_god_files(god_lines)
    java_layers = collect_java_layers()
    java_eps = collect_java_endpoints()
    py_routes = collect_py_routes()
    py_edges, py_cycles = collect_py_import_graph()
    mod_state = collect_module_state()
    violations = collect_layering_violations()
    fe = collect_frontend_structure()
    tests = collect_tests()
    eng = collect_engineering()
    debt = collect_debt()
    deps = collect_deps()
    sql = collect_sql()
    git = collect_git()

    L: list[str] = []
    w = L.append

    w("# 架构快照（机器生成）")
    w("")
    w("> 本文件由 `tools/arch_snapshot.py` 自动生成，**只陈述事实，不含评价**。")
    w("> 用途：作为 LLM 架构评审的输入底稿。请勿手工编辑——改代码后重跑。")
    w("")
    w(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"- Git：`{git['branch']}` @ `{git['commit']}`")
    w(f"- 上帝模块阈值：{god_lines} 行")
    w("")

    # 1 规模
    w("## 1. 规模总览")
    w("")
    w("| 端 | 源文件 | 代码行 | 语言分布 |")
    w("| --- | ---: | ---: | --- |")
    for name, s in scale.items():
        langs = " / ".join(f"{k} {v}" for k, v in sorted(s["by_lang"].items(), key=lambda x: -x[1]))
        w(f"| `{name}` | {s['files']} | {s['lines']} | {langs or '—'} |")
    w("")

    # 2 分层
    w("## 2. Java 分层落地情况")
    w("")
    if java_layers:
        w("| 层 | 文件数 | 类名 |")
        w("| --- | ---: | --- |")
        for layer, files in java_layers.items():
            names = ", ".join(Path(f).stem for f in files[:12])
            more = f" …(+{len(files) - 12})" if len(files) > 12 else ""
            w(f"| `{layer}` | {len(files)} | {names}{more} |")
    else:
        w("_未发现 Java 源码_")
    w("")

    # 3 对外接口
    w("## 3. 对外接口清单（Java Controller 实际声明）")
    w("")
    if java_eps:
        w(f"共 **{len(java_eps)}** 个端点。")
        w("")
        w("| 方法 | 路径 | 所在类 |")
        w("| --- | --- | --- |")
        for verb, path, cls in java_eps:
            w(f"| {verb} | `{path}` | {cls} |")
    else:
        w("_未发现 Controller 端点_")
    w("")

    # 4 内部接口
    w("## 4. 内部接口清单（Python 实际声明）")
    w("")
    if py_routes:
        w(f"共 **{len(py_routes)}** 个端点。")
        w("")
        w("| 方法 | 路径 | 定义位置 |")
        w("| --- | --- | --- |")
        for verb, path, f in py_routes:
            w(f"| {verb} | `{path}` | `{f}` |")
    else:
        w("_未发现 Python 路由_")
    w("")

    # 5 依赖
    w("## 5. 依赖清单")
    w("")
    if "java" in deps:
        w(f"**Java（pom.xml，{len(deps['java'])} 项）**：")
        w("")
        w("```")
        for d in deps["java"]:
            w(f"- {d}")
        w("```")
        w("")
    if "python" in deps:
        w(f"**Python（requirements.txt，{len(deps['python'])} 项）**：")
        w("")
        w("```")
        for d in deps["python"]:
            w(f"- {d}")
        w("```")
        w("")
    if "frontend_deps" in deps:
        w(f"**前端 dependencies（{len(deps['frontend_deps'])} 项）**：{', '.join(deps['frontend_deps'])}")
        w("")
        w(f"**前端 devDependencies（{len(deps['frontend_dev'])} 项）**：{', '.join(deps['frontend_dev'])}")
        w("")

    # 6 数据模型
    w("## 6. 数据库迁移（Flyway）")
    w("")
    if sql:
        w("| 迁移文件 | 规模 |")
        w("| --- | --- |")
        for name, size in sql:
            w(f"| `{name}` | {size} |")
    else:
        w("_未发现迁移脚本_")
    w("")

    # 7 测试
    w("## 7. 测试现状")
    w("")
    w("| 项 | 数值 |")
    w("| --- | ---: |")
    w(f"| Java 主源码文件 | {tests['java_main_files']} |")
    w(f"| Java 测试文件 | {tests['java_test_files']} |")
    w(f"| 前端测试文件 | {tests['frontend_test_files']} |")
    w(f"| 前端 spec 文件 | {tests['frontend_spec_files']} |")
    w(f"| Python 测试文件 | {tests['ai_test_files']} |")
    w(f"| 根 test/ Python 文件 | {tests['root_test_files']} |")
    w("")
    if tests["java_test_names"]:
        w(f"Java 测试类：{', '.join(tests['java_test_names'])}")
        w("")

    # 8 工程化
    w("## 8. 工程化配置")
    w("")
    w("| 项 | 是否存在 |")
    w("| --- | :---: |")
    for k, v in eng.items():
        w(f"| {k} | {'✅' if v else '❌'} |")
    w("")

    # 9 反模式
    w("## 9. 反模式机械扫描")
    w("")
    w(f"### 9.1 超长文件（≥{god_lines} 行）")
    w("")
    if gods:
        w("| 文件 | 行数 |")
        w("| --- | ---: |")
        for f, n in gods:
            w(f"| `{f}` | {n} |")
    else:
        w("_无_")
    w("")

    w("### 9.2 Python 模块 import 环")
    w("")
    if py_cycles:
        for comp in py_cycles:
            w(f"- ⚠️ 循环依赖：{' ⇄ '.join(comp)}")
    else:
        w("_未检出环_")
    w("")

    w("### 9.3 分层越界 / 反向依赖")
    w("")
    if violations:
        w("| 文件 | 违规 | 说明 |")
        w("| --- | --- | --- |")
        for f, rule, why in violations:
            w(f"| `{f}` | {rule} | {why} |")
    else:
        w("_未检出越层调用_")
    w("")

    w("### 9.4 Python 模块级可变全局状态")
    w("")
    if mod_state:
        w("| 文件 | 变量 |")
        w("| --- | --- |")
        for f, var in mod_state:
            w(f"| `{f}` | `{var}` |")
    else:
        w("_无_")
    w("")

    w("### 9.5 技术债标记")
    w("")
    if debt["counts"]:
        w("统计：" + "，".join(f"{k} {v}" for k, v in sorted(debt["counts"].items())))
        w("")
        for f, i, line in debt["samples"]:
            w(f"- `{f}:{i}` — `{line}`")
    else:
        w("_无_")
    w("")

    w("### 9.6 疑似硬编码凭据")
    w("")
    if debt["secrets"]:
        for f, i, line in debt["secrets"]:
            w(f"- `{f}:{i}` — `{line}`")
    else:
        w("_无_")
    w("")

    # 10 前端
    w("## 10. 前端结构")
    w("")
    for group, info in fe.items():
        w(f"### `{group}`（{info['count']} 个文件）")
        w("")
        w("```")
        for f in info["files"][:40]:
            w(f.replace("frontend/src/", ""))
        if info["count"] > 40:
            w(f"... 其余 {info['count'] - 40} 个")
        w("```")
        w("")

    w("---")
    w("")
    w("## 附：给 LLM 的阅读指引")
    w("")
    w("1. 先读 §1–§2 建立规模与分层印象。")
    w("2. 用 §3/§4 的端点清单与 `docs/api/openapi-*.yaml` 对账，找**声明与实际不一致**。")
    w("3. 用 §7 判断测试是否是「有测试」还是「测试覆盖了核心路径」。")
    w("4. §9 是机械证据，每条都要在评审里给出「影响 + 修法」。")
    w("5. 任何结论必须引用本文件的章节号或代码路径，禁止凭印象断言。")
    w("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成架构快照")
    ap.add_argument("--out", default="docs/03-架构评审/snapshot/架构快照.md")
    ap.add_argument("--god-lines", type=int, default=400, help="超长文件阈值，默认 400 行")
    args = ap.parse_args()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(args.god_lines), encoding="utf-8")
    print(f"[OK] 已生成 {rel(out)}")
    print(f"     规模：{out.stat().st_size} 字节 / {count_lines(out)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
