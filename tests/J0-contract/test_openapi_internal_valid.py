"""J0 契约门禁：内部契约 `docs/api/openapi-internal.yaml`。

覆盖 `docs/02-重构设计/04_后端开发提示词.md` §4 J0 门禁中与内部契约相关的条目：

1. YAML 可解析，operationId 唯一
2. 内部 8 条一条不少（架构规格 §7.4）
3. 每条 operation 有 200 与至少一个错误响应，且引用 envelope
4. 内部 snake_case 必须显式写在 YAML 里（不许「口头约定」）
5. 鉴权方案是 `X-Internal-Token` 请求头

本文件只读 `docs/api/`，不需要运行中的服务。
"""

from __future__ import annotations

import io
from functools import lru_cache

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from conftest import INTERNAL_YAML

pytestmark = pytest.mark.contract

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}

#: 内部 8 条（04 手册 §4 J0 清单 / 架构规格 §7.4）。
EXPECTED_OPERATIONS: set[tuple[str, str]] = {
    ("/internal/v1/chat/stream", "post"),
    ("/internal/v1/retrieve", "post"),
    ("/internal/v1/documents/parse", "post"),
    ("/internal/v1/ingest/{task_id}", "get"),
    ("/internal/v1/documents/{id}/status", "get"),
    ("/internal/v1/index/status", "get"),
    ("/internal/v1/eval/batch", "post"),
    ("/internal/v1/health", "get"),
}

#: 内部契约必须显式声明的 snake_case 字段（与对外 camelCase 的差异点）。
SNAKE_CASE_FIELDS = {
    "chunk_id",
    "doc_id",
    "doc_title",
    "heading_path",
    "excerpt",
    "score_stage",
}

ENVELOPE_REF = "#/components/schemas/ErrorEnvelope"


# --------------------------------------------------------------------------- 加载工具


@lru_cache(maxsize=1)
def contract() -> dict:
    assert INTERNAL_YAML.is_file(), f"契约文件缺失：{INTERNAL_YAML}"
    with io.open(INTERNAL_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def operations() -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for path, item in (contract().get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method in HTTP_METHODS:
                out.append((path, method, op))
    return out


def schemas() -> dict:
    return (contract().get("components") or {}).get("schemas") or {}


def resolve_pointer(doc: dict, ref: str) -> dict:
    assert ref.startswith("#/"), f"只支持文档内指针：{ref}"
    node: object = doc
    for part in ref[2:].split("/"):
        assert isinstance(node, dict) and part in node, f"指针解析失败：{ref}"
        node = node[part]
    assert isinstance(node, dict)
    return node


def deref(doc: dict, node: dict) -> dict:
    if isinstance(node, dict) and "$ref" in node:
        return resolve_pointer(doc, node["$ref"])
    return node


def validator_for(doc: dict, pointer: str) -> Draft202012Validator:
    resource = Resource.from_contents(doc, default_specification=DRAFT202012)
    registry = Registry().with_resource(uri="urn:doc", resource=resource)
    return Draft202012Validator({"$ref": f"urn:doc{pointer}"}, registry=registry)


# --------------------------------------------------------------------------- 1. 可解析 + operationId 唯一


def test_internal_yaml_parses_to_openapi_31() -> None:
    doc = contract()
    assert doc["openapi"] == "3.1.0", f"openapi 版本应为 3.1.0，实际 {doc['openapi']!r}"
    assert isinstance(doc.get("paths"), dict) and doc["paths"], "paths 不能为空"


def test_internal_yaml_declares_no_servers() -> None:
    assert "servers" not in contract(), "契约里不应出现 servers 字段"


def test_internal_operation_ids_unique_and_non_empty() -> None:
    ids = [op.get("operationId") for _, _, op in operations()]
    assert all(ids), f"存在缺失 operationId 的 operation：{ids}"
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"operationId 重复：{duplicates}"
    assert len(ids) == len(set(ids)) == 8, f"operationId 应有 8 个，实际 {len(ids)}"


# --------------------------------------------------------------------------- 2. 8 条一条不少


def test_internal_operations_match_checklist() -> None:
    got = {(path, method) for path, method, _ in operations()}
    missing = sorted(EXPECTED_OPERATIONS - got)
    extra = sorted(got - EXPECTED_OPERATIONS)
    assert not missing, f"缺少 operation：{missing}"
    assert not extra, f"多出 operation：{extra}"
    assert len(got) == 8


# --------------------------------------------------------------------------- 3. 200 + 错误响应都引用 envelope


def test_internal_every_operation_has_envelope_responses() -> None:
    doc = contract()
    problems: list[str] = []

    for path, method, op in operations():
        tag = f"{method.upper()} {path}"
        responses = op.get("responses") or {}

        if "200" not in responses:
            problems.append(f"{tag} 缺少 200 响应")
            continue

        content200 = (deref(doc, responses["200"]) or {}).get("content") or {}
        if "text/event-stream" not in content200:
            schema200 = (content200.get("application/json") or {}).get("schema") or {}
            ref200 = schema200.get("$ref", "")
            if not (
                ref200.startswith("#/components/schemas/Result")
                or ref200.startswith("#/components/schemas/Envelope")
            ):
                problems.append(f"{tag} 的 200 未引用 Result*/Envelope：{ref200 or schema200!r}")

        error_codes = [code for code in responses if str(code) != "200"]
        if not error_codes:
            problems.append(f"{tag} 缺少错误响应")
            continue

        for code in error_codes:
            content = (deref(doc, responses[code]) or {}).get("content") or {}
            schema = (content.get("application/json") or {}).get("schema") or {}
            if schema.get("$ref") != ENVELOPE_REF:
                problems.append(f"{tag} 的 {code} 未引用 {ENVELOPE_REF}：{schema.get('$ref')!r}")
                break

    assert not problems, "响应契约问题：\n" + "\n".join(problems)


def test_internal_every_operation_documents_error_codes() -> None:
    """每条 operation 都要带 `x-error-codes`，便于 Java 侧生成错误分支。"""
    problems = [
        f"{method.upper()} {path} 缺少 x-error-codes"
        for path, method, op in operations()
        if not op.get("x-error-codes")
    ]
    assert not problems, "缺少错误码声明：\n" + "\n".join(problems)


# --------------------------------------------------------------------------- 4. snake_case 显式性


def test_internal_citation_declares_snake_case_fields() -> None:
    citation = schemas().get("InternalCitation")
    assert citation, "缺少 components.schemas.InternalCitation"
    props = set((citation.get("properties") or {}).keys())
    missing = sorted(SNAKE_CASE_FIELDS - props)
    assert not missing, f"InternalCitation 缺少 snake_case 字段：{missing}"

    required = set(citation.get("required") or [])
    assert {"ref", "chunk_id", "doc_id", "doc_title", "heading_path", "excerpt"} <= required, (
        f"InternalCitation.required 不完整：{sorted(required)}"
    )


def test_internal_citation_has_no_camel_case_leakage() -> None:
    """内部契约不许混入对外 camelCase 字段名，否则两端生成器会各写一套。"""
    props = set(((schemas().get("InternalCitation") or {}).get("properties") or {}).keys())
    leaked = sorted(p for p in props if p in {"chunkId", "docId", "docTitle", "headingPath", "text"})
    assert not leaked, f"InternalCitation 混入了 camelCase 字段：{leaked}"


def test_internal_description_has_naming_map() -> None:
    """手册要求：内部允许 snake_case，但必须在 YAML 显式写清与对外的对应关系。"""
    description = (contract().get("info") or {}).get("description") or ""
    assert "excerpt" in description and "chunkId" in description, (
        "info.description 缺少内外命名对照表（至少覆盖 excerpt↔text、chunk_id↔chunkId）"
    )


# --------------------------------------------------------------------------- 5. 鉴权方案


def test_internal_security_scheme_is_header_token() -> None:
    doc = contract()
    security = doc.get("security") or []
    assert any("internalToken" in item for item in security), "内部契约未声明 internalToken 鉴权"

    scheme = ((doc.get("components") or {}).get("securitySchemes") or {}).get("internalToken")
    assert scheme, "缺少 securitySchemes.internalToken"
    assert scheme.get("type") == "apiKey", f"应为 apiKey，实际 {scheme.get('type')!r}"
    assert scheme.get("in") == "header", f"应在 header 传递，实际 {scheme.get('in')!r}"
    assert scheme.get("name") == "X-Internal-Token", f"头名应为 X-Internal-Token，实际 {scheme.get('name')!r}"


# --------------------------------------------------------------------------- 6. 关键实体形状


@pytest.mark.parametrize(
    ("name", "required"),
    [
        ("InternalChatRequest", {"question"}),
        ("InternalRetrieveRequest", set()),
        ("ParseAccepted", {"task_id", "doc_count"}),
        ("ParseDocumentItem", {"doc_id", "name", "text"}),
        ("IngestTask", {"task_id", "status", "stage", "progress", "doc_count", "chunk_count"}),
        ("DocumentStatus", {"doc_id", "status", "chunk_count"}),
        ("IndexManifest", {"status", "embedding_model", "chunk_size", "overlap"}),
        ("InternalEvalBatchRequest", {"cases", "mode", "k"}),
        ("InternalEvalCaseResult", {"question_id", "direct_passed", "rag_passed", "rag_sources"}),
        ("Health", {"status"}),
    ],
)
def test_internal_core_schema_required_fields(name: str, required: set[str]) -> None:
    schema = schemas().get(name)
    assert schema, f"缺少 components.schemas.{name}"
    actual = set(schema.get("required") or [])
    missing = sorted(required - actual)
    assert not missing, f"{name}.required 缺少：{missing}"


def test_internal_chat_request_validates_and_rejects_unknown_fields() -> None:
    validator = validator_for(contract(), "#/components/schemas/InternalChatRequest")

    good = {
        "question": "读书会通常在每周几几点举行？",
        "history": [{"role": "user", "content": "你好"}],
        "mode": "rag",
        "k": 3,
        "acl": [],
    }
    assert not list(validator.iter_errors(good)), "InternalChatRequest 拒绝了合法请求"

    bad = {**good, "chunkSize": 180}
    assert list(validator.iter_errors(bad)), "InternalChatRequest 未拒绝 camelCase 的陌生字段"

    bad_mode = {**good, "mode": "hybrid"}
    assert list(validator.iter_errors(bad_mode)), "InternalChatRequest 未拒绝非法 mode"

    bad_k = {**good, "k": 11}
    assert list(validator.iter_errors(bad_k)), "InternalChatRequest 未拒绝越界 k"


def test_internal_citation_accepts_both_ref_shapes() -> None:
    validator = validator_for(contract(), "#/components/schemas/InternalCitation")
    base = {
        "chunk_id": "D02-C001",
        "doc_id": "D02",
        "doc_title": "02_借阅规则.md",
        "heading_path": "# 星河读书会借阅规则",
        "excerpt": "已登记成员每人最多同时借阅4本普通图书，每本借期21天。",
        "start": 0,
        "end": 40,
        "score": 0.87,
        "score_stage": "rerank",
        "kind": "chunk",
        "verified": True,
    }
    for label, ref in [("整数 ref", 1), ("片段号 ref", "D02-C001")]:
        errors = list(validator.iter_errors({**base, "ref": ref}))
        assert not errors, f"InternalCitation 拒绝了 {label}：{errors[0].message}"

    assert list(validator.iter_errors({**base, "ref": 0})), "InternalCitation 未拒绝 ref=0"
    bad = {k: v for k, v in base.items() if k != "chunk_id"}
    bad["ref"] = 1
    assert list(validator.iter_errors(bad)), "InternalCitation 未拒绝缺失 chunk_id"
