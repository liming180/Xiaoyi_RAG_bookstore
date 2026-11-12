"""P7 真实验收用的环境装配（一次性小工具，不进产品代码）。

作用：
1. 生成/复用固定的 P7 凭据（JWT 密钥、内部令牌、双账号口令），写进
   `test-artifacts/p7-env.json`，让 Java / Python / 验收脚本三方读到同一份值；
2. 打印成 shell 可用的 `KEY=VALUE` 行，方便 pwsh 里 `$env:X = ...`。

为什么不用随机值：P7 要多次重启服务（尤其 D 项的「Python 重启后任务 FAILED」），
每次重启都换 JWT 密钥会让已签发的 token 失效，验收脚本就得反复登录。
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "test-artifacts" / "p7-env.json"

DEFAULTS = {
    "AUTH_JWT_SECRET": "",
    "AUTH_JWT_ISSUER": "xiaoyi-rag",
    "INTERNAL_TOKEN": "",
    "AUTH_BOOTSTRAP_USERNAME": "p7-a",
    "AUTH_BOOTSTRAP_PASSWORD": "p7-pass-alpha-001",
    "AUTH_SECONDARY_BOOTSTRAP_USERNAME": "p7-b",
    "AUTH_SECONDARY_BOOTSTRAP_PASSWORD": "p7-pass-bravo-002",
    "MYSQL_DATABASE": "xiaoyi_rag_gate",
    # Java 的资料落盘目录（J2 的 clean_storage 会清空它，所以必须和 AI 侧状态分家）
    "STORAGE_ROOT": str(REPO_ROOT / "test-artifacts" / "p7-storage" / "java"),
    # Python 的 ai-state.sqlite3 目录：服务运行期间文件被占用，不能被测试清理
    "AI_STORAGE_ROOT": str(REPO_ROOT / "test-artifacts" / "p7-storage" / "ai"),
    # 入库阶段节拍（毫秒）。Java 轮询间隔 1000ms，这里给 1200ms，
    # 让 parsing→splitting→embedding→summarizing→done 五段都能被观测到。
    "INGEST_STAGE_DELAY_MS": "1200",
}


def load() -> dict[str, str]:
    data: dict[str, str] = {}
    if OUT.exists():
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    merged = {**DEFAULTS, **{k: v for k, v in data.items() if v}}
    # 进程内环境变量优先（例如 local_mysql_up.py 会先把 MYSQL_DATABASE
    # 写进 os.environ 再调用这里，避免被 p7-env.json 里的旧值覆盖）。
    for key in DEFAULTS:
        override = os.getenv(key)
        if override:
            merged[key] = override
    # 迁移：早期版本把 Java 落盘与 AI 状态共用同一个目录，J2 的 clean_storage
    # 会删到正在被 uvicorn 占用的 ai-state.sqlite3（WinError 32）。这里自动分家。
    legacy_root = str(REPO_ROOT / "test-artifacts" / "p7-storage")
    if merged["STORAGE_ROOT"].rstrip("\\/") == legacy_root:
        merged["STORAGE_ROOT"] = DEFAULTS["STORAGE_ROOT"]
    if not merged.get("AI_STORAGE_ROOT"):
        merged["AI_STORAGE_ROOT"] = DEFAULTS["AI_STORAGE_ROOT"]
    if not merged["AUTH_JWT_SECRET"]:
        merged["AUTH_JWT_SECRET"] = base64.b64encode(os.urandom(48)).decode("ascii")
    if not merged["INTERNAL_TOKEN"]:
        merged["INTERNAL_TOKEN"] = "p7-" + secrets.token_hex(16)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return merged


if __name__ == "__main__":
    for key, value in load().items():
        print(f"{key}={value}")
