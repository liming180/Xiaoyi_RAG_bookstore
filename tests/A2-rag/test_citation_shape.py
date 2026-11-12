"""A2 引用形状：真实检索结果必须能被内部契约校验通过。

为什么要拿契约当裁判，而不是在测试里手写字段清单
------------------------------------------------
手写清单只能证明「测试和实现想的一样」，两边一起漂移就一起错。
`docs/api/openapi-internal.yaml` 是 Java 侧 `RealAiServiceClient` 反序列化的依据，
用 `Draft202012Validator` 直接校验真实响应，才是「引用能不能被消费方吃下」的证据。

覆盖：
* `InternalCitation` 逐条校验（含 `additionalProperties: false`）；
* `InternalTraceRow` 校验（`rank` / `retrieved` 是它比引用多出来的两项）；
* `InternalRetrieveResult` 整体校验（`citations` 与 `rows` 必须等长）；
* `chunk_id` pattern、`score_stage` enum、`ref` 连续性；
* `InternalChunkItem`（Java 落 chunk 表的线上形状）也过一遍契约。
"""

from __future__ import annotations

import io

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ai_app_loader import load_app
from conftest import INTERNAL_YAML

TOKEN = "a2-shape-token"
USER = 7

CORPUS = """# 星河读书会借阅规则

本资料是教学虚构规则。已登记成员每人最多同时借阅4本普通图书，每本借期21天。

## 续借

普通图书在到期前可申请续借1次，续借增加7天。已经逾期或被其他成员预约的图书不能续借。

## 工具书

工具书只能在书屋内阅览，不得外借。期刊合订本按年度装订，仅供馆内查阅。
"""


@pytest.fixture(scope="module")
def contract() -> dict:
    assert INTERNAL_YAML.is_file(), f"契约文件缺失：{INTERNAL_YAML}"
    with io.open(INTERNAL_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def validator_factory(contract):
    """返回「按 #/components/schemas/xxx 造校验器」的工厂，避免每个用例重复搭 Registry。"""

    def build(pointer: str) -> Draft202012Validator:
        resource = Resource.from_contents(contract, default_specification=DRAFT202012)
        registry = Registry().with_resource(uri="urn:doc", resource=resource)
        return Draft202012Validator({"$ref": f"urn:doc{pointer}"}, registry=registry)

    return build


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    module = load_app(monkeypatch, TOKEN)
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        yield client


def headers() -> dict[str, str]:
    return {"X-Internal-Token": TOKEN, "X-User-Id": str(USER)}


@pytest.fixture()
def built_task(client) -> str:
    """建一次库并等终态，返回 task_id。"""
    response = client.post(
        "/internal/v1/documents/parse",
        headers=headers(),
        json={
            "documents": [
                {"doc_id": "d1", "name": "rules.md", "title": "星河读书会借阅规则", "text": CORPUS}
            ],
            "chunk_size": 120,
            "overlap": 20,
            "submission_key": "sk-shape",
            "generation": "g-1",
        },
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["task_id"]
    task = client.get(f"/internal/v1/ingest/{task_id}", headers=headers()).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return task_id


def retrieve(client, k: int = 3) -> dict:
    response = client.post(
        "/internal/v1/retrieve",
        headers=headers(),
        json={"question": "每人最多借几本，借期多久", "k": k},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_each_citation_passes_internal_citation_schema(client, built_task, validator_factory):
    validator = validator_factory("#/components/schemas/InternalCitation")
    citations = retrieve(client)["citations"]

    assert citations, "本人刚建完库，检索不该为空"
    for citation in citations:
        errors = list(validator.iter_errors(citation))
        assert not errors, f"引用不合契约：{errors[0].message}；原文 {citation}"


def test_retrieve_result_passes_schema(client, built_task, validator_factory):
    validator = validator_factory("#/components/schemas/InternalRetrieveResult")
    payload = retrieve(client)

    errors = list(validator.iter_errors(payload))
    assert not errors, f"InternalRetrieveResult 不合契约：{errors[0].message}"
    assert len(payload["rows"]) == len(payload["citations"]), "轨迹行必须与引用一一对应"


def test_trace_rows_pass_schema_and_carry_rank(client, built_task, validator_factory):
    validator = validator_factory("#/components/schemas/InternalTraceRow")
    rows = retrieve(client)["rows"]

    assert rows, "检索命中时轨迹不能为空"
    for row in rows:
        errors = list(validator.iter_errors(row))
        assert not errors, f"轨迹行不合契约：{errors[0].message}；原文 {row}"
        assert "ref" not in row, "轨迹行不带 ref，带 ref 会被 additionalProperties:false 拒掉"
    assert [row["rank"] for row in rows] == list(range(1, len(rows) + 1))
    assert all(row["retrieved"] is True for row in rows)


def test_refs_are_contiguous_and_unique(client, built_task):
    citations = retrieve(client, k=3)["citations"]
    refs = [item["ref"] for item in citations]
    assert refs == list(range(1, len(refs) + 1)), refs
    chunk_ids = [item["chunk_id"] for item in citations]
    assert len(set(chunk_ids)) == len(chunk_ids), f"同一切片被塞了两次：{chunk_ids}"


def test_scores_are_bounded_and_stage_is_enum(client, built_task):
    for citation in retrieve(client)["citations"]:
        assert 0.0 <= citation["score"] <= 1.0, citation
        assert citation["score_stage"] in {"dense", "sparse", "rrf", "rerank"}, citation


def test_chunk_items_pass_schema(client, built_task, validator_factory):
    """Java 靠 `data.chunks` 落自己的 chunk 表，这份形状错了前端就永远是空列表。"""
    validator = validator_factory("#/components/schemas/InternalChunkItem")
    task = client.get(f"/internal/v1/ingest/{built_task}", headers=headers()).json()["data"]

    assert task["chunks"], "终态任务必须回传切片清单"
    for chunk in task["chunks"]:
        errors = list(validator.iter_errors(chunk))
        assert not errors, f"切片不合契约：{errors[0].message}；原文 {chunk}"


def test_list_mode_returns_whole_index_without_question(client, built_task):
    """列举模式（question 为空）用来给前端展示索引内容，必须回全量而不是空。"""
    response = client.post(
        "/internal/v1/retrieve",
        headers=headers(),
        json={"question": None, "k": 10, "list_mode": True},
    )
    assert response.status_code == 200, response.text
    citations = response.json()["data"]["citations"]

    assert citations, "建库成功后列举模式不该为空"
    assert all(item["score"] == 0.0 for item in citations), "列举不是检索，分数应置 0"
