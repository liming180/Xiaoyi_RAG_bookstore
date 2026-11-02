"""跨端黑盒验收测试的共享 fixture（仓库根 test/ 是唯一验收入口）。

本文件只放环境常量、轮询工具与客户端 fixture，**不写任何业务断言**。
规范来源：`docs/02-重构设计/04_后端开发提示词.md` §2.4。

设计约束
--------
- 不引入「未安装就 import 报错」的硬依赖：`pytest-asyncio` / `httpx-sse` / `pymysql`
  都用 try-import + skip 保护，让 `pytest test/J0-contract -q` 在只装了
  pytest + jsonschema + PyYAML 的机器上也能全绿。
- 禁止 `time.sleep`：轮询统一走 `wait_until()`。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

import pytest

T = TypeVar("T")

# --------------------------------------------------------------------------- 路径

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
DOCS_API = REPO_ROOT / "docs" / "api"
FIXTURES = TEST_DIR / "fixtures"

# --------------------------------------------------------------------------- 环境常量

BASE_JAVA = os.getenv("BASE_JAVA", "http://127.0.0.1:8080")
BASE_AI = os.getenv("BASE_AI", "http://127.0.0.1:8000")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "dev-internal-token")
#: 对外接口的开发态 Bearer；J2 换成真签发 JWT 后只需改这里。
JAVA_TOKEN = os.getenv("JAVA_TOKEN", "dev-token")

#: 数据库连接：口令一律走用户级环境变量 `MYSQL_PASSWORD`，仓库里不出现明文。
#: 默认值与本机 MySQL80（3306）+ `xiaoyi_rag` 库对齐，见 docs/README.md 关键约定第 1 条。


def env_or_user_registry(name: str, default: str = "") -> str:
    """先读进程环境变量，读不到再回落到 Windows「用户变量」（注册表 HKCU\\Environment）。

    为什么要这条回落：`MYSQL_PASSWORD` 是用户级变量，而已经启动的进程（含 pytest 所在的
    这个 shell、IDE 里的终端）不会自动继承后来新设的值，直接 `os.getenv` 会拿到空串，
    导致 J2 里所有需要直连库的用例被静默 skip —— 那等于门禁没验。
    """
    value = os.getenv(name)
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except OSError:
            return default
    return default


DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = env_or_user_registry("MYSQL_USER", "root")
DB_PASSWORD = env_or_user_registry("MYSQL_PASSWORD")
DB_NAME = os.getenv("MYSQL_DATABASE", "xiaoyi_rag")
DB_URL = os.getenv("DB_URL", f"mysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

#: 契约文件绝对路径，供 J0-contract 用例直接引用。
PUBLIC_YAML = DOCS_API / "openapi-public.yaml"
INTERNAL_YAML = DOCS_API / "openapi-internal.yaml"
ENVELOPE_SCHEMA = DOCS_API / "envelope.schema.json"
ERROR_CODES_MD = DOCS_API / "error-codes.md"

#: 资料落盘根目录，与 `xiaoyi.storage.root` 对齐（默认 `./storage`，相对 server-java 工作目录）。
#: J2 用例要断言「文件真的写出去了」「删除后真的没了」，所以必须能定位到磁盘。
STORAGE_ROOT = Path(
    os.getenv("STORAGE_ROOT", str(REPO_ROOT / "server-java" / "storage"))
).resolve()

# --------------------------------------------------------------------------- pytest 配置

#: `asyncio_mode = auto`（pytest 9 + pytest-asyncio 需要显式声明）。
#: pytest-asyncio 未安装时不注册该 ini 选项，否则 pytest 会因未知 ini key 报错。
try:  # pragma: no cover - 取决于本机是否装了 pytest-asyncio
    import pytest_asyncio  # noqa: F401
except ImportError:  # pragma: no cover
    HAVE_PYTEST_ASYNCIO = False
else:  # pragma: no cover
    HAVE_PYTEST_ASYNCIO = True


def pytest_configure(config: pytest.Config) -> None:
    if HAVE_PYTEST_ASYNCIO:
        config.option.asyncio_mode = "auto"
        config.addinivalue_line(
            "markers", "asyncio: 异步用例（pytest-asyncio, asyncio_mode=auto）"
        )
    config.addinivalue_line("markers", "contract: 契约层用例，不依赖运行中的服务")
    config.addinivalue_line("markers", "live: 需要真实 Java / Python 进程")


# --------------------------------------------------------------------------- 轮询工具


def wait_until(
    fn: Callable[[], T],
    timeout: float = 15.0,
    interval: float = 0.1,
    message: str = "",
) -> T:
    """反复调用 `fn()` 直到返回真值，返回该真值；超时抛 AssertionError。

    用法：``wait_until(lambda: task["status"] == "SUCCEEDED", timeout=15)``。
    内部固定 0.1s 间隔，**替代 time.sleep**（手册 §2.3 明令禁止 sleep）。
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    last_exc: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            last = fn()
        except BaseException as exc:  # noqa: BLE001 - 轮询期间吞掉瞬时异常
            last_exc = exc
            last = None
        else:
            if last:
                return last  # type: ignore[return-value]
            last_exc = None
        time.sleep(interval)
    detail = message or getattr(fn, "__name__", repr(fn))
    raise AssertionError(
        f"wait_until 超时（{timeout}s）：{detail}；最后一次返回值={last!r}，异常={last_exc!r}"
    )


# --------------------------------------------------------------------------- 客户端 fixture


@pytest.fixture(scope="session")
def java_base() -> str:
    return BASE_JAVA


@pytest.fixture(scope="session")
def ai_base() -> str:
    return BASE_AI


@pytest.fixture(scope="session")
def internal_token() -> str:
    return INTERNAL_TOKEN


@pytest.fixture(scope="session")
def java_client():
    """指向 Java 的 httpx.Client（带开发态 Bearer）。

    J1 起 AuthInterceptor 要求 `Authorization: Bearer <token>`，
    J2 会把 token 换成真签发的 JWT，这里先固定 dev 值。
    """
    httpx = pytest.importorskip("httpx", reason="需要 httpx")
    with httpx.Client(
        base_url=BASE_JAVA,
        timeout=60.0,
        headers={"Authorization": f"Bearer {JAVA_TOKEN}"},
    ) as client:
        yield client


@pytest.fixture(scope="session")
def bare_client():
    """不带 Authorization 的裸客户端，专门验 401 路径。"""
    httpx = pytest.importorskip("httpx", reason="需要 httpx")
    with httpx.Client(base_url=BASE_JAVA, timeout=60.0) as client:
        yield client


@pytest.fixture(scope="session")
def ai_client():
    """指向 Python 的 httpx.Client，自带 X-Internal-Token。"""
    httpx = pytest.importorskip("httpx", reason="需要 httpx")
    with httpx.Client(
        base_url=BASE_AI,
        timeout=60.0,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    ) as client:
        yield client


def _parse_sse(text: str, event_cls):
    """把 SSE 文本解成事件对象列表（`event_cls(event=..., data=...)`）。

    为什么自己解而不用 `httpx_sse.SSEDecoder`：它只存在于 `httpx_sse._decoders`（私有模块），
    公开 API 只有 `connect_sse` / `ServerSentEvent`。自己解 20 行，反而更稳。

    规则（WHATWG EventSource）：空行分帧；`field: value` 冒号后一个空格可省；
    以 `:` 开头是注释；`data` 多行用 `\\n` 拼接；没有 `data` 的帧不派发。
    """
    events: list[Any] = []
    name: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal name, data_lines
        if data_lines:
            events.append(event_cls(event=name, data="\n".join(data_lines)))
        name = None
        data_lines = []

    for raw in text.splitlines():
        if not raw:
            flush()
            continue
        if raw.startswith(":"):
            continue
        field, _, value = raw.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            data_lines.append(value)
    flush()
    return events


def read_sse(
    payload: dict[str, Any],
    token: str | None = JAVA_TOKEN,
    path: str = "/api/v1/chat/stream",
    timeout: float = 60.0,
) -> tuple[int, str, list[Any], str]:
    """发一次 SSE 请求，返回 `(HTTP 状态码, Content-Type, 事件列表, 原始响应文本)`。

    为什么不用 `httpx_sse.connect_sse`：它在响应不是 `text/event-stream` 时直接抛异常，
    而 J3 的失败分支（400 / 401 / 404）恰恰要读状态码与 JSON 信封。这里先普通 POST 拿全量响应，
    再按 Content-Type 决定要不要解事件 —— 两条路径都能断言。
    """
    httpx = pytest.importorskip("httpx", reason="需要 httpx")
    httpx_sse = pytest.importorskip("httpx_sse", reason="需要 httpx-sse")

    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(base_url=BASE_JAVA, timeout=timeout) as client:
        response = client.post(path, json=payload, headers=headers)

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("text/event-stream"):
        return response.status_code, content_type, [], response.text

    return (
        response.status_code,
        content_type,
        _parse_sse(response.text, httpx_sse.ServerSentEvent),
        response.text,
    )


@pytest.fixture(scope="session")
def sse_stream():
    """读取 `POST /api/v1/chat/stream` 并返回事件列表的可调用对象。

    默认带上开发态 Bearer（`/chat/stream` 不在 AuthInterceptor 白名单里，不带必 401）。
    需要看 HTTP 状态码与 Content-Type 时用 `read_sse()`。
    """
    pytest.importorskip("httpx", reason="需要 httpx")
    pytest.importorskip("httpx_sse", reason="需要 httpx-sse")

    def _stream(
        payload: dict[str, Any],
        token: str | None = JAVA_TOKEN,
        path: str = "/api/v1/chat/stream",
    ) -> list[Any]:
        status, _content_type, events, text = read_sse(payload, token=token, path=path)
        assert status == 200, f"SSE 请求应 200，实际 {status}：{text[:400]}"
        return events

    return _stream


# --------------------------------------------------------------------------- 数据清理


def _clear_storage() -> None:
    """删掉 `STORAGE_ROOT` 下的全部条目（不删根目录本身，服务启动时已建好）。"""
    if not STORAGE_ROOT.exists():
        return
    import shutil

    for entry in STORAGE_ROOT.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def reset_ingest_state() -> bool:
    """清空建库相关状态：`chunk` / `index_task` / `document` 三张表 + `storage/` 下的资料文件。

    返回是否真的执行了（没装 pymysql 或连不上库时返回 False）。

    为什么必须连 `document` 一起清
    ------------------------------
    `IndexServiceImpl.rebuild()` 会把**所有**未删资料塞进一次 `parseDocuments` 请求，
    `triggerParse` 再逐个读磁盘。只清 `chunk` / `index_task` 的话，历史资料会随着用例
    数量线性累积：J4 首轮 29 个用例一共堆了几十份资料，单次建库要重新解析全部文件，
    整体跑了 4248 秒（70 分钟），并且让 15s 的 `wait_until` 直接超时。

    为什么还要清磁盘
    ----------------
    `clean_db` 只删表行不删文件，残留目录会一直留在 `server-java/storage/` 下；
    清干净后「上传 → 落盘 → 删除」这类断言才不会被上一轮的残留误导。
    """
    try:
        import pymysql  # type: ignore
    except ImportError:
        return False

    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            autocommit=True,
        )
    except Exception:  # noqa: BLE001 - 无 DB 环境下静默降级
        return False

    try:
        with conn.cursor() as cur:
            for table in ("chunk", "index_task", "document"):
                cur.execute(f"DELETE FROM {table}")  # noqa: S608 - 表名来自常量
    finally:
        conn.close()

    _clear_storage()
    return True


@pytest.fixture
def clean_db():
    """每个用例前后清空 message / conversation / document / index_task / eval_run。

    只在显式装了数据库驱动且 `DB_URL` 可连通时生效；否则用例拿到的是 None，
    自己按「无 DB」路径处理（例如只打 HTTP、依赖服务端自带清理）。
    """
    try:
        import pymysql  # type: ignore  # noqa: F401
    except ImportError:
        yield None
        return

    tables: Iterable[str] = (
        "message",
        "conversation",
        "chunk",
        "document",
        "index_task",
        "eval_run",
    )

    def _truncate() -> None:
        import pymysql  # type: ignore

        conn = pymysql.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(f"DELETE FROM {table}")  # noqa: S608 - 表名来自常量
        finally:
            conn.close()
        _clear_storage()

    try:
        _truncate()
    except Exception:  # noqa: BLE001 - 无 DB 环境下静默降级
        yield None
        return

    yield _truncate

    try:
        _truncate()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- 通用工具


def assert_envelope(body: Any) -> dict:
    """断言响应体是统一信封，返回 body 本身，便于链式断言。"""
    assert isinstance(body, dict), f"响应体不是对象：{body!r}"
    for key in ("code", "message", "data", "timestamp"):
        assert key in body, f"信封缺少字段 {key}：{body!r}"
    assert isinstance(body["code"], int), f"code 不是整数：{body!r}"
    assert isinstance(body["message"], str), f"message 不是字符串：{body!r}"
    assert isinstance(body["timestamp"], int), f"timestamp 不是整数：{body!r}"
    return body
