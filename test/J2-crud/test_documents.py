r"""J2 文档 CRUD：上传五道校验、启停用状态流转、删除后磁盘文件消失。

手册 §6「测试（test/J2-crud/ 下写）」第 3 条要覆盖：
合法 md 上传成功 / 2.1MB 被拒 / .pdf 被拒 / 空正文被拒 / `../evil.md` 不写出去 /
启停用状态流转 / 删除后磁盘文件不存在。

两条文档在「路径穿越」上的措辞不同，这里按更精确的一方实现并两头都验：

- `docs/api/error-codes.md` §12（J0 契约，reason 文案「不得改写」）：
  文件名含 `../`、`..\`、`/` 时按 `Path(name).getFileName()` 截末段后再校验，**不报错**。
  所以 `../evil.md` → `evil.md` → 后缀合法 → 收下，落盘位置仍在 storage 根内。
- 手册 §6 测试条：`../evil.md` 「被拒且未写出目录」。
  真正被拒的情形是截末段后为空（如 `../`）或截完仍不合法（如 `../evil.pdf`）。

于是本文件分两条断言：
`test_path_traversal_never_writes_outside_storage` 验安全属性（外面一个字节都不许落地），
`test_path_only_filename_is_skipped` 验「被拒」这一侧。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES, REPO_ROOT, STORAGE_ROOT

pytestmark = pytest.mark.live

DOCUMENT_KEYS = {
    "id",
    "name",
    "title",
    "tags",
    "version",
    "charCount",
    "chunkCount",
    "status",
    "verified",
    "updatedAt",
}

REASON_EXT = "只接受 .md / .txt 文件"
REASON_SIZE = "文件超过 2MB"
REASON_EMPTY = "文件没有正文"
REASON_ENCODING = "文件编码不是 UTF-8"


@pytest.fixture
def clean_storage():
    """清空落盘目录，让「文件真的写出去了 / 真的删掉了」可以被断言。"""
    if STORAGE_ROOT.exists():
        for child in STORAGE_ROOT.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    yield STORAGE_ROOT
    for child in STORAGE_ROOT.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _upload(client, name: str, content: bytes, content_type: str = "text/markdown"):
    return client.post("/api/v1/documents", files=[("files", (name, content, content_type))])


def _skipped_by_name(payload: dict, name: str) -> dict:
    hits = [row for row in payload["data"]["skipped"] if row["name"] == name]
    assert hits, f"skipped 里没有 {name}：{payload['data']['skipped']}"
    return hits[0]


def test_upload_valid_markdown_is_accepted(java_client, clean_db, clean_storage):
    """合法 md：accepted 一条，status=UPLOADING，title 取正文首个一级标题。"""
    body = "# 借阅规则\n\n普通图书最多同时借阅 4 本，借期 21 天。\n"

    resp = _upload(java_client, "02_借阅规则.md", body.encode("utf-8"))

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    accepted = payload["data"]["accepted"]
    skipped = payload["data"]["skipped"]
    assert len(accepted) == 1, payload["data"]
    assert skipped == [], payload["data"]

    doc = accepted[0]
    assert set(doc) == DOCUMENT_KEYS, f"字段集不对：{sorted(doc)}"
    assert doc["name"] == "02_借阅规则.md", "name 是文件名（含后缀）"
    assert doc["title"] == "借阅规则", "title 应取正文首个一级标题"
    assert doc["status"] == "UPLOADING", "上传完只到 UPLOADING，解析是 J4 的异步任务"
    assert doc["version"] == "v1"
    assert doc["verified"] is True
    assert doc["charCount"] == len(body)
    assert doc["chunkCount"] == 0, "J2 还没切分"

    on_disk = clean_storage / doc["id"] / "02_借阅规则.md"
    assert on_disk.is_file(), f"磁盘上应有 {on_disk}"
    assert on_disk.read_text(encoding="utf-8") == body


def test_upload_without_h1_falls_back_to_filename(java_client, clean_db, clean_storage):
    """没有一级标题时 title 回落文件名（手册 §6「filename 与 title 分离」）。"""
    resp = _upload(java_client, "无标题.txt", "这里没有一级标题，只有正文。\n".encode("utf-8"))

    payload = resp.json()
    assert payload["code"] == 0, payload
    doc = payload["data"]["accepted"][0]
    assert doc["title"] == "无标题.txt", doc


def test_upload_oversize_is_skipped_with_reason(java_client, clean_db, clean_storage):
    """2.1MB 文件：整批仍 code=0，该文件进 skipped 且 reason 是「文件超过 2MB」。"""
    big = FIXTURES / "sample_big.md"
    assert big.is_file(), f"缺少 fixture：{big}"
    assert big.stat().st_size > 2 * 1024 * 1024, "fixture 必须真的超过 2MB"

    resp = _upload(java_client, "sample_big.md", big.read_bytes())

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, "单份文件超限不算接口失败"
    assert payload["data"]["accepted"] == [], payload["data"]
    assert _skipped_by_name(payload, "sample_big.md")["reason"] == REASON_SIZE


def test_upload_pdf_is_skipped_with_reason(java_client, clean_db, clean_storage):
    """.pdf 不在允许后缀里：进 skipped，reason 是「只接受 .md / .txt 文件」。"""
    resp = _upload(java_client, "photo.pdf", b"%PDF-1.7\nfake\n", "application/pdf")

    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["accepted"] == [], payload["data"]
    assert _skipped_by_name(payload, "photo.pdf")["reason"] == REASON_EXT


def test_upload_blank_content_is_skipped_with_reason(java_client, clean_db, clean_storage):
    """只有空白字符的正文：进 skipped，reason 是「文件没有正文」。"""
    resp = _upload(java_client, "empty.txt", b"   \n\n\t\n  ", "text/plain")

    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["accepted"] == [], payload["data"]
    assert _skipped_by_name(payload, "empty.txt")["reason"] == REASON_EMPTY


def test_upload_non_utf8_is_skipped_with_reason(java_client, clean_db, clean_storage):
    """GBK 字节流：严格 UTF-8 解码失败，进 skipped，reason 是「文件编码不是 UTF-8」。"""
    gbk = "读书会每周六举行".encode("gbk")

    resp = _upload(java_client, "gbk.txt", gbk, "text/plain")

    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["accepted"] == [], payload["data"]
    assert _skipped_by_name(payload, "gbk.txt")["reason"] == REASON_ENCODING


def test_mixed_batch_keeps_good_files(java_client, clean_db, clean_storage):
    """一批里有好有坏：好的收下，坏的进 skipped，互不影响（这是「不中断整批」的核心）。"""
    files = [
        ("files", ("good.md", "# 好文件\n\n正文。\n".encode("utf-8"), "text/markdown")),
        ("files", ("bad.pdf", b"%PDF-1.7\n", "application/pdf")),
        ("files", ("good2.txt", "纯文本正文。\n".encode("utf-8"), "text/plain")),
    ]

    resp = java_client.post("/api/v1/documents", files=files)

    payload = resp.json()
    assert payload["code"] == 0, payload
    accepted_names = [row["name"] for row in payload["data"]["accepted"]]
    skipped_names = [row["name"] for row in payload["data"]["skipped"]]
    assert accepted_names == ["good.md", "good2.txt"], accepted_names
    assert skipped_names == ["bad.pdf"], skipped_names


def test_upload_without_files_returns_40001(java_client, clean_db, clean_storage):
    """`files` 缺失是唯一会让整批失败的情况（error-codes.md §12）。"""
    resp = java_client.post("/api/v1/documents", files=[("other", ("a.md", b"# a\n", "text/markdown"))])

    assert resp.status_code == 400, resp.text
    payload = resp.json()
    assert payload["code"] == 40001, payload
    assert payload["data"] is None, payload


def test_path_traversal_never_writes_outside_storage(java_client, clean_db, clean_storage):
    """`../evil.md`：按契约截末段收下，但绝不能有任何字节落到 storage 根之外。"""
    outside_candidates = [
        REPO_ROOT / "evil.md",
        REPO_ROOT / "server-java" / "evil.md",
        REPO_ROOT / "storage" / "evil.md",
        clean_storage.parent / "evil.md",
    ]
    for path in outside_candidates:
        path.unlink(missing_ok=True)

    resp = _upload(java_client, "../evil.md", "# evil\n\n正文。\n".encode("utf-8"))

    payload = resp.json()
    assert payload["code"] == 0, payload

    for path in outside_candidates:
        assert not path.exists(), f"路径穿越写出了目录：{path}"

    accepted = payload["data"]["accepted"]
    if accepted:
        doc = accepted[0]
        assert doc["name"] == "evil.md", f"name 必须是截取后的纯文件名：{doc['name']}"
        assert "/" not in doc["name"] and ".." not in doc["name"], doc["name"]
        stored = clean_storage / doc["id"] / "evil.md"
        assert stored.is_file(), f"应落在 storage 根内：{stored}"
        assert clean_storage.resolve() in stored.resolve().parents, "落盘位置必须在 storage 根内"
    else:
        assert _skipped_by_name(payload, "../evil.md")["reason"] == REASON_EXT


def test_path_only_filename_is_skipped(java_client, clean_db, clean_storage):
    """`../` 截末段后为空 → 无文件名可用 → 进 skipped（这是「被拒」的那一侧）。"""
    resp = _upload(java_client, "../", "# x\n\n正文。\n".encode("utf-8"))

    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["accepted"] == [], payload["data"]
    assert payload["data"]["skipped"][0]["reason"] == REASON_EXT


def test_document_enable_disable_round_trip(java_client, clean_db, clean_storage):
    """启停用：status=DISABLED 停用，改回 INDEXED 启用。

    前端 `setDocumentEnabled` 走的就是 `PUT /documents/{id} {status}`，
    见 frontend/src/api/modules/knowledge.ts。
    """
    doc = _upload(java_client, "toggle.md", "# 启停用\n\n正文。\n".encode("utf-8")).json()["data"][
        "accepted"
    ][0]

    off = java_client.put(f"/api/v1/documents/{doc['id']}", json={"status": "DISABLED"})

    assert off.status_code == 200, off.text
    off_payload = off.json()
    assert off_payload["code"] == 0, off_payload
    assert off_payload["data"]["status"] == "DISABLED", off_payload["data"]
    assert set(off_payload["data"]) == DOCUMENT_KEYS, sorted(off_payload["data"])

    on = java_client.put(f"/api/v1/documents/{doc['id']}", json={"status": "INDEXED"})

    assert on.status_code == 200, on.text
    assert on.json()["data"]["status"] == "INDEXED", on.json()["data"]


def test_update_document_title_and_tags(java_client, clean_db, clean_storage):
    """PUT 只允许改 title / tags / version / status 四类字段。"""
    doc = _upload(java_client, "rename.md", "# 原标题\n\n正文。\n".encode("utf-8")).json()["data"][
        "accepted"
    ][0]

    resp = java_client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "新标题", "tags": ["借阅", "规则"], "version": "v2"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "新标题", data
    assert data["tags"] == ["借阅", "规则"], data
    assert data["version"] == "v2", data
    assert data["name"] == "rename.md", "改标题不该改文件名"


def test_update_unknown_document_returns_40401(java_client, clean_db, clean_storage):
    """改不存在的资料回 40401（不是 40406）。"""
    resp = java_client.put("/api/v1/documents/999999", json={"title": "x"})

    assert resp.status_code == 404, resp.text
    payload = resp.json()
    assert payload["code"] == 40401, payload
    assert payload["data"] is None, payload


def test_delete_document_removes_row_and_file(java_client, clean_db, clean_storage):
    """删除后：列表里没有它、磁盘目录没了、库行是软删。"""
    pymysql = pytest.importorskip("pymysql", reason="需要 pymysql 直查库")
    if clean_db is None:
        pytest.skip("数据库不可用，无法校验软删")

    doc = _upload(java_client, "todelete.md", "# 待删\n\n正文。\n".encode("utf-8")).json()["data"][
        "accepted"
    ][0]
    directory = clean_storage / doc["id"]
    assert directory.is_dir(), f"删除前应有目录：{directory}"

    resp = java_client.delete(f"/api/v1/documents/{doc['id']}")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"] is None, payload

    assert not directory.exists(), f"删除后磁盘目录应消失：{directory}"

    listed = java_client.get("/api/v1/documents").json()["data"]
    assert doc["id"] not in [row["id"] for row in listed], "删除后不该出现在列表里"

    from conftest import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

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
            cur.execute("SELECT deleted FROM document WHERE id = %s", (int(doc["id"]),))
            row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None, "资料是软删，行应保留"
    assert row[0] == 1, f"deleted 应为 1，实际 {row[0]}"


def test_delete_unknown_document_returns_40401(java_client, clean_db, clean_storage):
    """删不存在的资料回 40401。"""
    resp = java_client.delete("/api/v1/documents/999999")

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == 40401, resp.text


def test_upload_marks_indexed_documents_stale(java_client, clean_db, clean_storage):
    """任何文档增删改都要把已建好的索引标脏（手册 §6 第 5 条）。

    做法：先把一份资料手工改成 INDEXED（模拟 J4 建完库），再上传一份新资料，
    断言那份旧资料被推回 NEEDS_REBUILD。
    """
    pymysql = pytest.importorskip("pymysql", reason="需要 pymysql 直查库")
    if clean_db is None:
        pytest.skip("数据库不可用，无法校验标脏")

    old = _upload(java_client, "old.md", "# 旧资料\n\n正文。\n".encode("utf-8")).json()["data"][
        "accepted"
    ][0]

    from conftest import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

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
            cur.execute(
                "UPDATE document SET status = 'INDEXED' WHERE id = %s", (int(old["id"]),)
            )
    finally:
        conn.close()

    _upload(java_client, "new.md", "# 新资料\n\n正文。\n".encode("utf-8"))

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
            cur.execute("SELECT status FROM document WHERE id = %s", (int(old["id"]),))
            row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None, "旧资料应还在"
    assert row[0] == "NEEDS_REBUILD", f"语料变了应把索引标脏，实际 {row[0]}"


def test_storage_root_is_inside_server_java(java_client, clean_db, clean_storage):
    """落盘根目录必须在 server-java 之下，防止误配到仓库根污染工作区。"""
    assert STORAGE_ROOT.name == "storage", STORAGE_ROOT
    assert STORAGE_ROOT.parent.name == "server-java", STORAGE_ROOT
    assert Path(STORAGE_ROOT).is_dir(), STORAGE_ROOT
