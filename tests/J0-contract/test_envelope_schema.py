"""J0 契约门禁：`docs/api/envelope.schema.json`。

覆盖 `docs/02-重构设计/04_后端开发提示词.md` §4 J0 门禁中与信封相关的条目：

1. `envelope.schema.json` 自身是合法的 JSON Schema 2020-12
2. 合法信封（含 `data: {}` / `data: null`）能通过校验
3. 缺字段、类型错、多余字段必须被拒
4. `$defs.ErrorEnvelope` 只接受 `data: null`
5. `$defs.Citation` 同时容纳整数 `ref` 与片段号 `ref`
6. `test/fixtures/envelope.schema.json` 与 `docs/api/` 下的副本逐字节一致

本文件只读契约文件，不需要运行中的服务。
"""

from __future__ import annotations

import json
from functools import lru_cache

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from conftest import ENVELOPE_SCHEMA, FIXTURES

pytestmark = pytest.mark.contract

FIXTURE_SCHEMA = FIXTURES / "envelope.schema.json"

REQUIRED_FIELDS = {"code", "message", "data", "timestamp"}


# --------------------------------------------------------------------------- 加载工具


@lru_cache(maxsize=1)
def schema() -> dict:
    assert ENVELOPE_SCHEMA.is_file(), f"契约文件缺失：{ENVELOPE_SCHEMA}"
    return json.loads(ENVELOPE_SCHEMA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def validator() -> Draft202012Validator:
    return Draft202012Validator(schema())


def validator_for(pointer: str) -> Draft202012Validator:
    """以整份 schema 为 $ref 解析根，校验 `$defs` 里的子 schema。

    不能把子 schema 单独交给 Validator：`$defs.ErrorEnvelope` 里写 `$ref: "#"`，
    脱离根文档后 `#` 会指回它自己，形成自环 → RecursionError。
    """
    doc = schema()
    resource = Resource.from_contents(doc, default_specification=DRAFT202012)
    registry = Registry().with_resource(uri="urn:doc", resource=resource)
    return Draft202012Validator({"$ref": f"urn:doc{pointer}"}, registry=registry)


def citation_base() -> dict:
    return {
        "chunkId": "D02-C001",
        "docId": "D02",
        "docTitle": "02_借阅规则.md",
        "headingPath": "# 星河读书会借阅规则",
        "text": "已登记成员每人最多同时借阅4本普通图书，每本借期21天。",
        "start": 0,
        "end": 40,
        "score": 0.87,
        "kind": "chunk",
        "verified": True,
    }


# --------------------------------------------------------------------------- 1. 合法 schema


def test_envelope_schema_is_valid_2020_12() -> None:
    Draft202012Validator.check_schema(schema())


def test_envelope_schema_declares_required_fields() -> None:
    doc = schema()
    assert doc.get("type") == "object", f"顶层 type 应为 object，实际 {doc.get('type')!r}"
    assert set(doc.get("required") or []) == REQUIRED_FIELDS, (
        f"required 应为 {sorted(REQUIRED_FIELDS)}，实际 {sorted(doc.get('required') or [])}"
    )
    assert doc.get("additionalProperties") is False, "顶层应禁止额外字段"


def test_envelope_schema_matches_fixture_copy() -> None:
    """`test/fixtures/envelope.schema.json` 是 docs/api/ 的副本，必须逐字节一致。"""
    assert FIXTURE_SCHEMA.is_file(), f"fixtures 副本缺失：{FIXTURE_SCHEMA}"
    assert FIXTURE_SCHEMA.read_bytes() == ENVELOPE_SCHEMA.read_bytes(), (
        "test/fixtures/envelope.schema.json 与 docs/api/envelope.schema.json 不一致，"
        "请重新复制：Copy-Item docs/api/envelope.schema.json test/fixtures/ -Force"
    )


# --------------------------------------------------------------------------- 2. 合法信封


@pytest.mark.parametrize(
    ("label", "instance"),
    [
        (
            "成功 · data 是对象",
            {"code": 0, "message": "success", "data": {"token": "abc"}, "timestamp": 1730000000},
        ),
        (
            "成功 · data 是数组",
            {"code": 0, "message": "success", "data": [1, 2, 3], "timestamp": 1730000000},
        ),
        (
            "成功 · data 是 null（删除类接口）",
            {"code": 0, "message": "success", "data": None, "timestamp": 1730000000},
        ),
        (
            "成功 · data 是字符串",
            {"code": 0, "message": "success", "data": "ok", "timestamp": 1730000000},
        ),
        (
            "失败 · 40401",
            {"code": 40401, "message": "资料不存在", "data": None, "timestamp": 1730000000},
        ),
    ],
)
def test_envelope_accepts_valid_bodies(label: str, instance: dict) -> None:
    errors = sorted(validator().iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, f"合法信封被拒（{label}）：{errors[0].message}"


# --------------------------------------------------------------------------- 3. 非法信封


@pytest.mark.parametrize(
    ("label", "instance"),
    [
        ("缺 data", {"code": 0, "message": "success", "timestamp": 1}),
        ("缺 timestamp", {"code": 0, "message": "success", "data": None}),
        ("缺 message", {"code": 0, "data": None, "timestamp": 1}),
        ("code 是字符串", {"code": "0", "message": "s", "data": None, "timestamp": 1}),
        # 注意：`0.0` 在 JSON Schema 2020-12 里是合法 integer（规范定义 integer 为
        # 「没有小数部分的数」），故不能用它做反例；用真正带小数的值。
        ("code 带小数", {"code": 40001.5, "message": "s", "data": None, "timestamp": 1}),
        ("timestamp 是浮点", {"code": 0, "message": "s", "data": None, "timestamp": 1.5}),
        ("timestamp 是字符串", {"code": 0, "message": "s", "data": None, "timestamp": "2024-01-01"}),
        ("message 是数字", {"code": 0, "message": 1, "data": None, "timestamp": 1}),
        ("多余字段", {"code": 0, "message": "s", "data": None, "timestamp": 1, "traceId": "x"}),
        ("不是对象", ["code", 0]),
    ],
)
def test_envelope_rejects_invalid_bodies(label: str, instance) -> None:
    assert list(validator().iter_errors(instance)), f"非法信封未被拒（{label}）"


# --------------------------------------------------------------------------- 4. ErrorEnvelope


def test_error_envelope_accepts_null_data() -> None:
    ev = validator_for("#/$defs/ErrorEnvelope")
    instance = {"code": 40401, "message": "资料不存在", "data": None, "timestamp": 1730000000}
    assert not list(ev.iter_errors(instance)), "ErrorEnvelope 拒绝了合法错误信封"


@pytest.mark.parametrize(
    ("label", "data"),
    [("data 是空对象", {}), ("data 是空数组", []), ("data 是字符串", "x")],
)
def test_error_envelope_rejects_non_null_data(label: str, data) -> None:
    ev = validator_for("#/$defs/ErrorEnvelope")
    instance = {"code": 40401, "message": "资料不存在", "data": data, "timestamp": 1}
    assert list(ev.iter_errors(instance)), f"ErrorEnvelope 未拒绝 {label}"


def test_error_envelope_requires_data_key() -> None:
    ev = validator_for("#/$defs/ErrorEnvelope")
    instance = {"code": 40401, "message": "资料不存在", "timestamp": 1}
    assert list(ev.iter_errors(instance)), "ErrorEnvelope 未拒绝缺失 data 字段的信封"


# --------------------------------------------------------------------------- 5. Citation 双形状


def test_citation_definition_present_and_strict() -> None:
    citation = (schema().get("$defs") or {}).get("Citation")
    assert citation, "$defs 缺少 Citation"
    assert citation.get("additionalProperties") is False, "Citation 应禁止额外字段"
    required = set(citation.get("required") or [])
    assert {"ref", "chunkId", "docId", "docTitle", "headingPath", "text"} <= required, (
        f"Citation.required 不完整：{sorted(required)}"
    )


@pytest.mark.parametrize(
    ("label", "instance"),
    [
        ("整数 ref", {**citation_base(), "ref": 1}),
        ("片段号 ref", {**citation_base(), "ref": "D02-C001"}),
        ("整数 ref + 无 stage", {**citation_base(), "ref": 2}),
        ("整数 ref + stage", {**citation_base(), "ref": 3, "stage": "rerank"}),
        ("kind = summary", {**citation_base(), "ref": 4, "kind": "summary"}),
        ("kind = rule", {**citation_base(), "ref": 5, "kind": "rule"}),
    ],
)
def test_citation_def_accepts_both_ref_shapes(label: str, instance: dict) -> None:
    cv = validator_for("#/$defs/Citation")
    errors = sorted(cv.iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, f"Citation 拒绝了 {label}：{errors[0].message}"


@pytest.mark.parametrize(
    ("label", "instance"),
    [
        ("ref = 0", {**citation_base(), "ref": 0}),
        ("ref 是空串", {**citation_base(), "ref": ""}),
        ("chunkId 格式非法", {**citation_base(), "ref": 1, "chunkId": "XXX"}),
        ("kind 非法", {**citation_base(), "ref": 1, "kind": "bogus"}),
        ("stage 非法", {**citation_base(), "ref": 1, "stage": "bogus"}),
        ("score 越界", {**citation_base(), "ref": 1, "score": 2}),
        ("缺 chunkId", {k: v for k, v in {**citation_base(), "ref": 1}.items() if k != "chunkId"}),
    ],
)
def test_citation_def_rejects_invalid_instances(label: str, instance: dict) -> None:
    cv = validator_for("#/$defs/Citation")
    assert list(cv.iter_errors(instance)), f"Citation 未拒绝 {label}"


# --------------------------------------------------------------------------- 6. TraceRow / RetrievalTrace


def test_retrieval_trace_requires_rows_and_bounds() -> None:
    trace = (schema().get("$defs") or {}).get("RetrievalTrace")
    assert trace, "$defs 缺少 RetrievalTrace"
    required = set(trace.get("required") or [])
    assert {"question", "k", "chunkSize", "overlap", "rows"} <= required, (
        f"RetrievalTrace.required 不完整：{sorted(required)}"
    )

    tv = validator_for("#/$defs/RetrievalTrace")
    row = {
        "rank": 1,
        "chunkId": "D02-C001",
        "docId": "D02",
        "docTitle": "02_借阅规则.md",
        "headingPath": "# 星河读书会借阅规则",
        "text": "已登记成员每人最多同时借阅4本普通图书。",
        "start": 0,
        "end": 30,
        "score": 0.87,
        "retrieved": True,
        "kind": "chunk",
        "verified": True,
    }
    good = {"question": "最多借几本？", "k": 3, "chunkSize": 180, "overlap": 30, "rows": [row]}
    assert not list(tv.iter_errors(good)), "RetrievalTrace 拒绝了合法实例"

    bad_k = {**good, "k": 11}
    assert list(tv.iter_errors(bad_k)), "RetrievalTrace 未拒绝越界 k"

    bad_size = {**good, "chunkSize": 49}
    assert list(tv.iter_errors(bad_size)), "RetrievalTrace 未拒绝越界 chunkSize"
