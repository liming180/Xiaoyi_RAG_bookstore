"""J0 契约门禁：对外契约 `docs/api/openapi-public.yaml`。

覆盖 `docs/02-重构设计/04_后端开发提示词.md` §4 J0 门禁中与对外契约相关的条目：

1. YAML 能被 `yaml.safe_load` 解析，且无重复 operationId
2. 对外 28 条一条不少（§7.3 的 15 行是子集，必须全部包含）
3. 每条 operation 有 200 与至少一个错误响应，且错误响应引用 envelope schema
4. Citation schema 同时容纳 `{ref: 1, ...}` 与 `{ref: "D02-C001", ...}`

本文件只读 `docs/api/`，不需要任何运行中的服务，可离线全绿。
"""

from __future__ import annotations

import io
import re
from functools import lru_cache

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from conftest import ERROR_CODES_MD, PUBLIC_YAML

pytestmark = pytest.mark.contract

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}

#: 对外 28 条（04 手册 §4 J0 清单，逐条核对）。
EXPECTED_OPERATIONS: set[tuple[str, str]] = {
    ("/api/v1/auth/login", "post"),
    ("/api/v1/auth/profile", "get"),
    ("/api/v1/conversations", "get"),
    ("/api/v1/conversations", "post"),
    ("/api/v1/conversations/{id}", "delete"),
    ("/api/v1/conversations/{id}/messages", "get"),
    ("/api/v1/conversations/{id}/messages", "delete"),
    ("/api/v1/chat/stream", "post"),
    ("/api/v1/messages/{id}/trace", "get"),
    ("/api/v1/documents", "get"),
    ("/api/v1/documents", "post"),
    ("/api/v1/documents/{id}", "put"),
    ("/api/v1/documents/{id}", "delete"),
    ("/api/v1/index/status", "get"),
    ("/api/v1/index/rebuild", "post"),
    ("/api/v1/index/tasks/{id}", "get"),
    ("/api/v1/chunks", "get"),
    ("/api/v1/eval/questions", "get"),
    ("/api/v1/eval/batch", "post"),
    ("/api/v1/eval/runs", "get"),
    ("/api/v1/eval/runs/{id}", "get"),
    ("/api/v1/messages/{id}/feedback", "post"),
    ("/api/v1/feedback/summary", "get"),
    ("/api/v1/eval/candidates", "get"),
    ("/api/v1/eval/candidates/{id}/decision", "post"),
    ("/api/v1/eval/experiments", "post"),
    ("/api/v1/eval/experiments/{id}", "get"),
    ("/api/v1/eval/experiments/{id}/report", "get"),
}

#: 架构规格 §7.3 的 15 行表格展开成 (path, method)，必须全部被 28 条覆盖。
SPEC_SUBSET: set[tuple[str, str]] = {
    ("/api/v1/auth/login", "post"),
    ("/api/v1/conversations", "get"),
    ("/api/v1/conversations", "post"),
    ("/api/v1/conversations/{id}/messages", "get"),
    ("/api/v1/conversations/{id}/messages", "delete"),
    ("/api/v1/chat/stream", "post"),
    ("/api/v1/messages/{id}/trace", "get"),
    ("/api/v1/documents", "get"),
    ("/api/v1/documents", "post"),
    ("/api/v1/documents/{id}", "put"),
    ("/api/v1/documents/{id}", "delete"),
    ("/api/v1/index/status", "get"),
    ("/api/v1/index/rebuild", "post"),
    ("/api/v1/index/tasks/{id}", "get"),
    ("/api/v1/chunks", "get"),
    ("/api/v1/eval/batch", "post"),
    ("/api/v1/eval/runs", "get"),
}

ENVELOPE_REF = "#/components/schemas/ErrorEnvelope"


# --------------------------------------------------------------------------- 加载工具


@lru_cache(maxsize=1)
def contract() -> dict:
    """读并解析对外契约（同一 session 内只读一次）。"""
    assert PUBLIC_YAML.is_file(), f"契约文件缺失：{PUBLIC_YAML}"
    with io.open(PUBLIC_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def operations() -> list[tuple[str, str, dict]]:
    """展开成 `[(path, method, operation), ...]`。"""
    out: list[tuple[str, str, dict]] = []
    for path, item in (contract().get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method in HTTP_METHODS:
                out.append((path, method, op))
    return out


def resolve_pointer(doc: dict, ref: str) -> dict:
    """解析文档内部的 `#/a/b/c` 指针。"""
    assert ref.startswith("#/"), f"只支持文档内指针：{ref}"
    node: object = doc
    for part in ref[2:].split("/"):
        assert isinstance(node, dict) and part in node, f"指针解析失败：{ref}"
        node = node[part]
    assert isinstance(node, dict)
    return node


def deref(doc: dict, node: dict) -> dict:
    """单层 `$ref` 解引用。"""
    if isinstance(node, dict) and "$ref" in node:
        return resolve_pointer(doc, node["$ref"])
    return node


def validator_for(doc: dict, pointer: str) -> Draft202012Validator:
    """以整份文档为 $ref 解析根，校验目标子 schema。

    不能把子 schema 单独交给 Validator：`$defs.ErrorEnvelope` 里写 `$ref: "#"`，
    脱离根文档后 `#` 会指回它自己，形成自环 → RecursionError。
    """
    resource = Resource.from_contents(doc, default_specification=DRAFT202012)
    registry = Registry().with_resource(uri="urn:doc", resource=resource)
    return Draft202012Validator({"$ref": f"urn:doc{pointer}"}, registry=registry)


@lru_cache(maxsize=1)
def documented_codes() -> set[int]:
    """从 `docs/api/error-codes.md` 的表格里抽出全部错误码。

    表格行形如 ``| `40001` | `参数不合法` | 400 | ... |``；成功码是 ``| `0` | `success` |``，
    所以位数范围取 1..5。
    """
    assert ERROR_CODES_MD.is_file(), f"错误码文档缺失：{ERROR_CODES_MD}"
    text = ERROR_CODES_MD.read_text(encoding="utf-8")
    return {int(m) for m in re.findall(r"^\|\s*`(\d{1,5})`\s*\|", text, re.MULTILINE)}


# --------------------------------------------------------------------------- 1. 可解析 + operationId 唯一


def test_public_yaml_parses_to_openapi_31() -> None:
    doc = contract()
    assert doc["openapi"] == "3.1.0", f"openapi 版本应为 3.1.0，实际 {doc['openapi']!r}"
    assert isinstance(doc.get("paths"), dict) and doc["paths"], "paths 不能为空"


def test_public_yaml_declares_no_servers() -> None:
    """手册禁止在 YAML 写 server 地址（服务名由部署配置注入）。"""
    assert "servers" not in contract(), "契约里不应出现 servers 字段"


def test_public_operation_ids_unique_and_non_empty() -> None:
    ids = [op.get("operationId") for _, _, op in operations()]
    assert all(ids), f"存在缺失 operationId 的 operation：{ids}"
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"operationId 重复：{duplicates}"
    assert len(ids) == len(set(ids)) == 28, f"operationId 应有 28 个，实际 {len(ids)}"


# --------------------------------------------------------------------------- 2. 28 条一条不少


def test_public_operations_match_checklist() -> None:
    got = {(path, method) for path, method, _ in operations()}
    missing = sorted(EXPECTED_OPERATIONS - got)
    extra = sorted(got - EXPECTED_OPERATIONS)
    assert not missing, f"缺少 operation：{missing}"
    assert not extra, f"多出 operation：{extra}"
    assert len(got) == 28


def test_public_operations_cover_spec_subset() -> None:
    """架构规格 §7.3 的 15 行表格必须被 28 条完全覆盖。"""
    got = {(path, method) for path, method, _ in operations()}
    missing = sorted(SPEC_SUBSET - got)
    assert not missing, f"§7.3 子集未覆盖：{missing}"


# --------------------------------------------------------------------------- 3. 200 + 错误响应都引用 envelope


def test_public_every_operation_has_envelope_responses() -> None:
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


def test_public_error_codes_are_documented() -> None:
    """每个 operation 的 `x-error-codes` 都必须在 error-codes.md 里有定义。"""
    known = documented_codes()
    assert 0 in known, "error-codes.md 必须定义成功码 0"

    unknown: dict[str, list[int]] = {}
    for path, method, op in operations():
        for code in op.get("x-error-codes") or []:
            if int(code) not in known:
                unknown.setdefault(f"{method.upper()} {path}", []).append(int(code))
    assert not unknown, f"未在 error-codes.md 定义的错误码：{unknown}"


# --------------------------------------------------------------------------- 4. Citation 双形状


def citation_schema() -> dict:
    return (contract().get("components") or {}).get("schemas", {}).get("Citation") or {}


def sample_citation() -> dict:
    return {
        "chunkId": "D02-C001",
        "docId": "D02",
        "docTitle": "02_借阅规则.md",
        "headingPath": "# 星河读书会借阅规则",
        "text": "已登记成员每人最多同时借阅4本普通图书，每本借期21天。",
        "start": 0,
        "end": 40,
        "score": 0.87,
        "stage": "rerank",
        "kind": "chunk",
        "verified": True,
    }


def test_citation_schema_exists() -> None:
    schema = citation_schema()
    assert schema, "缺少 components.schemas.Citation"
    required = set(schema.get("required") or [])
    assert {"ref", "chunkId", "docId", "docTitle", "headingPath", "text"} <= required, (
        f"Citation.required 不完整：{sorted(required)}"
    )


@pytest.mark.parametrize(
    ("label", "instance"),
    [
        ("整数 ref（对外主用）", {**sample_citation(), "ref": 1}),
        ("片段号 ref（规格 §7.5 示例）", {**sample_citation(), "ref": "D02-C001"}),
        ("无 stage（可选字段）", {**sample_citation(), "ref": 2}),
        ("summary 类型", {**sample_citation(), "ref": 3, "kind": "summary"}),
        ("rule 类型", {**sample_citation(), "ref": 4, "kind": "rule"}),
    ],
)
def test_citation_accepts_valid_instances(label: str, instance: dict) -> None:
    validator = validator_for(contract(), "#/components/schemas/Citation")
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, f"Citation 拒绝了 {label}：{errors[0].message}"


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("缺失 chunkId", lambda c: {k: v for k, v in c.items() if k != "chunkId"}),
        ("chunkId 格式非法", lambda c: {**c, "chunkId": "XXX"}),
        ("ref 为 0", lambda c: {**c, "ref": 0}),
        ("kind 不在枚举内", lambda c: {**c, "kind": "unknown"}),
        ("stage 不在枚举内", lambda c: {**c, "stage": "bogus"}),
        ("score 越界", lambda c: {**c, "score": 1.5}),
    ],
)
def test_citation_rejects_invalid_instances(label: str, mutate) -> None:
    validator = validator_for(contract(), "#/components/schemas/Citation")
    instance = mutate({**sample_citation(), "ref": 1})
    assert list(validator.iter_errors(instance)), f"Citation 未拒绝 {label}"
