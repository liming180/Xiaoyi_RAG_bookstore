r"""J2 资料数上限：第 100 份在上传口被前置拒绝（N6 收口，施工单 §11.6 遗留）。

契约里 `chunk_id` 形如 `D\d{2}-C\d{3}`，文档号只有两位十进制，所以一个用户**同时**最多 99 份。
这条约束原本只在 Python 建库时才撞上：用户传完第 100 份 → 点建库 → 等几秒 → 看到一句
「编号不够用」。上传接口据此把闸门前移，**先告诉他不能收，好过收下了再退**。

两条断言分别钉两侧：
- 满了就拒，且是 400 + 40001，文案里带「99」让用户知道上限是多少；
- 删掉一份后能再传一份 —— 上限统计只看 `deleted = false` 的行，把软删的算进来会表现成
  「删了还是传不上」，那种 bug 用户没法自查。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

MAX_DOCS = 99

LIMIT_HINT = "资料数已达上限"


def _md(index: int) -> bytes:
    """每份内容必须唯一，否则会走 sha256 去重、不占名额。"""
    return f"# 资料 {index:03d}\n\n这是第 {index} 份资料的正文，用于占满 99 个编号。\n".encode()


def _upload_many(client, start: int, count: int):
    files = [
        ("files", (f"limit_{i:03d}.md", _md(i), "text/markdown"))
        for i in range(start, start + count)
    ]
    return client.post("/api/v1/documents", files=files)


def test_100th_document_is_rejected_before_storage(java_client, clean_db):
    """一次传满 99 份可以，第 100 份回 400 + 40001（且这时候还没写盘、没建库）。"""
    filled = _upload_many(java_client, start=1, count=MAX_DOCS)

    assert filled.status_code == 200, filled.text
    payload = filled.json()
    assert payload["code"] == 0, payload
    accepted = payload["data"]["accepted"]
    assert len(accepted) == MAX_DOCS, f"应一次收下 99 份，实际 {len(accepted)}"
    assert payload["data"]["skipped"] == [], payload["data"]["skipped"]

    overflow = java_client.post(
        "/api/v1/documents",
        files=[("files", ("overflow.md", _md(999), "text/markdown"))],
    )

    assert overflow.status_code == 400, overflow.text
    body = overflow.json()
    assert body["code"] == 40001, body
    assert body["data"] is None, body
    assert LIMIT_HINT in body["message"], body["message"]
    assert str(MAX_DOCS) in body["message"], f"文案要说清上限是多少：{body['message']}"

    listed = java_client.get("/api/v1/documents")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["data"]) == MAX_DOCS, "被拒的那份不能偷偷入库"


def test_deleting_one_document_frees_a_slot(java_client, clean_db):
    """删掉一份后能再传一份：上限统计只看 deleted = false 的行。"""
    filled = _upload_many(java_client, start=1, count=MAX_DOCS).json()["data"]["accepted"]
    victim = filled[0]["id"]

    removed = java_client.delete(f"/api/v1/documents/{victim}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["code"] == 0, removed.text

    # 列表是立即生效的（软删 + deleted = false 过滤），不需要等建库。
    remaining = java_client.get("/api/v1/documents").json()["data"]
    assert len(remaining) == MAX_DOCS - 1, len(remaining)
    assert all(row["id"] != victim for row in remaining)

    replacement = java_client.post(
        "/api/v1/documents",
        files=[("files", ("replacement.md", _md(1000), "text/markdown"))],
    )

    assert replacement.status_code == 200, replacement.text
    body = replacement.json()
    assert body["code"] == 0, body
    assert len(body["data"]["accepted"]) == 1, body["data"]
    assert body["data"]["accepted"][0]["name"] == "replacement.md"


def test_limit_is_per_user_not_global(java_client, java_client_b, clean_db):
    """A 满了不影响 B：上限按 uploaded_by 统计。"""
    _upload_many(java_client, start=1, count=MAX_DOCS)

    b_list = java_client_b.get("/api/v1/documents")
    assert b_list.status_code == 200, b_list.text
    assert b_list.json()["data"] == [], "另一个用户不该看到 A 的资料"

    b_upload = java_client_b.post(
        "/api/v1/documents",
        files=[("files", ("b_first.md", _md(2000), "text/markdown"))],
    )
    assert b_upload.status_code == 200, b_upload.text
    assert len(b_upload.json()["data"]["accepted"]) == 1


def test_rejection_happens_before_batch_validation(java_client, clean_db):
    """满了之后连「本来就会被 skip 的坏文件」也一并拒：整批前置，不逐份放行。

    这条钉的是`requireCapacity` 在校验循环**之前**调用 —— 若挪到循环里，用户会看到
    「坏文件被 skip、好文件被 40001 拒绝」这种半截行为，比整批拒绝更难理解。
    """
    _upload_many(java_client, start=1, count=MAX_DOCS)

    resp = java_client.post(
        "/api/v1/documents",
        files=[
            ("files", ("bad.pdf", b"%PDF-1.7\n", "application/pdf")),
            ("files", ("good.md", _md(3000), "text/markdown")),
        ],
    )

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == 40001, body
    assert body["data"] is None, "前置拒绝时不返回 accepted/skipped，避免前端以为「坏文件处理过了」"


def test_under_limit_still_reports_skipped_per_file(java_client, clean_db):
    """没满的时候行为不变：坏文件仍逐份进 skipped，整批 code=0。"""
    resp = java_client.post(
        "/api/v1/documents",
        files=[
            ("files", ("ok.md", _md(1), "text/markdown")),
            ("files", ("bad.pdf", b"%PDF-1.7\n", "application/pdf")),
        ],
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    assert [row["name"] for row in body["data"]["accepted"]] == ["ok.md"]
    assert [row["name"] for row in body["data"]["skipped"]] == ["bad.pdf"]
