#!/usr/bin/env python
"""设置 / 验证 Milvus 的 root 密码。

为什么需要这个脚本：Milvus 的 root 密码有两个容易踩的坑，合起来能把自己锁在门外 ——

1. **默认密码不是空，而是 `Milvus`**（见镜像内 `/milvus/configs/milvus.yaml` 的
   `common.security.defaultRootPassword`）。网上很多资料写「on-premises 默认密码为空」，
   那是旧版本；本项目用的 milvusdb/milvus:v3.0.0 默认是 `Milvus`。按「空密码」去连会一直
   `Fail connecting to server ... illegal connection params`，看不出真实原因。
2. **`authorizationEnabled` 是热加载的**，改 `user.yaml` 不用重启容器。所以「改配置 → 设密码」
   这两个动作用错顺序时，会经历一段「鉴权已开、密码还没设好」的窗口，谁连都失败。
   正确顺序必须是：**鉴权关闭时设好密码 → 再打开鉴权**。

Milvus 没有「忘记密码」的自助入口，锁死后只能进容器改配置重启，因此本脚本把顺序检查
做在每一步之前，并在最后同时验证「新密码能连」和「默认密码被拒」。

用法：

    python tools/setup_milvus_auth.py --status
    python tools/setup_milvus_auth.py --set-password
    python tools/setup_milvus_auth.py --set-password --old-password Milvus
    python tools/setup_milvus_auth.py --verify

凭证来源（按优先级）：命令行 > 环境变量 > deploy/local-mysql.env。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "deploy" / "local-mysql.env"

DEFAULT_USER = "root"
DEFAULT_URI = os.environ.get("MILVUS_URI", "http://127.0.0.1:19530")
# 镜像出厂默认值。不是空字符串 —— 这是本脚本最重要的一条知识。
FACTORY_PASSWORD = "Milvus"


def read_env_file() -> dict[str, str]:
    """极简 .env 解析：只认 KEY=VALUE，忽略注释与空行。不引入 dotenv 依赖。"""
    out: dict[str, str] = {}
    if not ENV_FILE.exists():
        return out
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def resolve(cli_value: str | None, env_key: str, default: str | None = None) -> str:
    if cli_value:
        return cli_value
    if os.environ.get(env_key):
        return os.environ[env_key]
    value = read_env_file().get(env_key)
    if value:
        return value
    if default is not None:
        return default
    raise SystemExit(
        f"找不到 {env_key}：请在 deploy/local-mysql.env 里加一行\n"
        f"    {env_key}=你的值\n"
        f"或用命令行参数传入。"
    )


def connect(uri: str, user: str | None = None, password: str | None = None):
    try:
        from pymilvus import MilvusClient
    except ImportError as exc:
        raise SystemExit("当前 Python 没有 pymilvus。装一下：pip install 'pymilvus>=2.5'") from exc

    kwargs: dict[str, object] = {"uri": uri}
    if user:
        kwargs["user"] = user
    if password is not None:
        kwargs["password"] = password
    return MilvusClient(**kwargs)


def try_connect(uri: str, user: str, password: str) -> tuple[bool, object]:
    """连一次，返回 (是否成功, 集合列表或异常)。不抛异常，交给调用方决定怎么讲。"""
    try:
        client = connect(uri, user=user, password=password)
        collections = client.list_collections()
        client.close()
        return True, collections
    except Exception as exc:  # noqa: BLE001 - 连接失败的原因由 Milvus 给出，原样转述
        return False, exc


def cmd_status(args: argparse.Namespace) -> int:
    """把「鉴权开没开、哪个密码能进」一次讲清楚。排查时先跑这个。"""
    user = resolve(args.user, "MILVUS_USER", DEFAULT_USER)
    target = resolve(args.password, "MILVUS_PASSWORD")

    print(f"URI: {args.uri}   user: {user}\n")
    for label, candidate in [
        (f"目标密码（来自 local-mysql.env）", target),
        (f"镜像默认密码 {FACTORY_PASSWORD!r}", FACTORY_PASSWORD),
        ("空密码", ""),
    ]:
        ok, detail = try_connect(args.uri, user, candidate)
        if ok:
            print(f"  [OK]   {label} -> 集合 {detail}")
        else:
            print(f"  [DENY] {label}")

    print(
        "\n怎么读这个结果：\n"
        "  - 只有「目标密码」OK          -> 鉴权已生效且密码已设好，正常状态\n"
        "  - 只有「默认密码 / 空密码」OK  -> 鉴权没开，或开了但还没设密码（跑 --set-password）\n"
        "  - 三个都 DENY                 -> 密码被改成别的值了；进容器改 user.yaml 关掉鉴权再设\n"
    )
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    user = resolve(args.user, "MILVUS_USER", DEFAULT_USER)
    new_password = resolve(args.password, "MILVUS_PASSWORD")
    old_password = resolve(args.old_password, "MILVUS_OLD_PASSWORD", FACTORY_PASSWORD)

    if len(new_password) < 8:
        raise SystemExit("密码至少 8 位（Milvus 要求，且太短没意义）")
    if new_password == old_password:
        raise SystemExit("新密码与旧密码相同，无需设置")

    print(f"[1/3] 用旧密码连一次（user={user}, old={old_password!r}）")
    ok, detail = try_connect(args.uri, user, old_password)
    if not ok:
        print(f"      旧密码连不上：{str(detail)[:120]}")
        print(
            "\n      两种可能：\n"
            f"        a) 密码已经被改过 —— 用 --old-password 指定当前真实密码；\n"
            f"        b) 鉴权已开启且当前密码不是 {old_password!r} —— 进容器把\n"
            "           deploy/milvus/user.yaml 的 authorizationEnabled 改回 false，等约 10 秒热加载后重试。\n"
            "      不确定现状时先跑：python tools/setup_milvus_auth.py --status"
        )
        return 1
    print(f"      [OK] 连接成功，集合 {detail}")

    print(f"[2/3] 改密码")
    client = connect(args.uri, user=user, password=old_password)
    try:
        client.update_password(
            user_name=user, old_password=old_password, new_password=new_password
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"      改密码失败：{exc}") from exc
    finally:
        client.close()
    print("      已提交")

    print("[3/3] 用新密码验证")
    ok, detail = try_connect(args.uri, user, new_password)
    if not ok:
        raise SystemExit(f"      新密码连不上（异常）：{str(detail)[:160]}")
    print(f"      [OK] 新密码可用，集合 {detail}")

    print(
        "\n下一步：确认 deploy/milvus/user.yaml 里 common.security.authorizationEnabled 为 true。\n"
        "它是热加载的，改完等约 10 秒即可，不必重启容器。\n"
        "然后跑：python tools/setup_milvus_auth.py --verify"
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """两条都要过：新密码能连 + 默认/空密码被拒。任一不符就返回非 0。"""
    user = resolve(args.user, "MILVUS_USER", DEFAULT_USER)
    password = resolve(args.password, "MILVUS_PASSWORD")

    ok_target, detail = try_connect(args.uri, user, password)
    print(f"[1/3] 目标密码连接 {user}")
    if ok_target:
        print(f"      [OK] 成功，集合 {detail}")
    else:
        print(f"      [FAIL] {str(detail)[:120]}")
        print("      先跑 --status 看当前哪个密码能进")
        return 1

    failures = 0
    for label, candidate in [("镜像默认密码", FACTORY_PASSWORD), ("空密码", "")]:
        ok, _ = try_connect(args.uri, user, candidate)
        print(f"[2/3] {label} 应被拒")
        if ok:
            print("      [FAIL] 竟然连上了 -> 鉴权没生效，检查 authorizationEnabled")
            failures += 1
        else:
            print("      [OK] 已拒绝")

    print("[3/3] 结论")
    if failures:
        print("      鉴权未完全生效，见上面 FAIL 项")
        return 1
    print("      鉴权已生效：只有目标密码能连，默认密码与空密码均被拒。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="设置 / 验证 Milvus root 密码")
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=None, help="默认 root")
    parser.add_argument("--password", default=None, help="目标密码，默认读 MILVUS_PASSWORD")
    parser.add_argument(
        "--old-password",
        default=None,
        help=f"当前密码，默认镜像出厂值 {FACTORY_PASSWORD!r}",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="看鉴权状态与哪个密码能进")
    group.add_argument("--set-password", action="store_true", help="改密码")
    group.add_argument("--verify", action="store_true", help="验证鉴权是否生效")
    args = parser.parse_args()

    if args.status:
        return cmd_status(args)
    if args.set_password:
        return cmd_set_password(args)
    return cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
