# RAG 核心实现审查报告

> 审查范围：`backend/ai-api/app/core/rag/` 下的 `reranker.py`（203 行）与 `splitter.py`（204 行）
> 审查时间：2026-11-12

## 一、结论

两个模块整体工程质量**高于预期**：注释里有实测数据支撑、边界条件考虑周全、降级路径明确。但发现 **3 个真实缺陷，已全部修复**，其中 1 个会直接影响评测结论的可信度。

| 编号 | 位置 | 严重度 | 状态 |
|---|---|---|---|
| R1 | `LexicalReranker.rerank` 违背「保序」契约 | **高** | 已修 |
| R2 | `score_stage` 标注与实际行为不符 | 中 | 已修 |
| R3 | `chunk_size=180` 未经调参实验 | 中 | 待定 |

## 二、R1：LexicalReranker 违背保序契约（已修）

### 问题

类注释明确写着：

> 所以降级路径的契约是「不比不降级更差」：**顺序原样保留**，词项分只用于解释与并列消歧。

但实现是：

```python
ranked.sort(key=lambda row: (-row["score"], -row["lexical_score"], row["chunk_id"]))
```

主排序键是 `-score`，次键是 `-lexical_score`。**当 score 相同时，lexical_score 变成实际排序键**，推翻了 RRF 用 `chunk_id` 建立的确定性顺序。

### 复现

```python
rows = [
    {'chunk_id': 'D01-C001', 'excerpt': '完全无关的内容',   'score': 0.05},
    {'chunk_id': 'D01-C002', 'excerpt': '借书最多几本 四本', 'score': 0.05},
]
out = LexicalReranker().rerank('借书最多几本', rows, 2)

# 修复前
输入: ['D01-C001', 'D01-C002']
输出: ['D01-C002', 'D01-C001']    ← 顺序被改变
```

### 影响

RRF 融合**经常产出同分候选**——两路名次之和相等是常态（如 dense 第 1 + sparse 第 3 = rrf 第 2 + 第 2）。此时降级路径会静默重排，导致：

1. 「hybrid 档位」的实际行为与注释不符，代码可读性受损
2. 评测时 hybrid 与 rrf 的组合关系不可预测，掩盖真实差异

### 修复

去掉 `sort`，顺序原样返回，`lexical_score` 仅作为解释字段随行带出：

```python
annotated = [{...补充 rrf_score / lexical_score / score...} for row in rows]
# 不排序：annotated 的顺序就是入参 rows 的顺序（RRF 已排好）
return annotated[: max(0, k)]
```

## 三、R2：score_stage 标注失真（已修）

### 问题

`ingest.py` 在 hybrid 路径末尾**无条件**写 `stage="rerank"`：

```python
result = pipeline.recall(runtime.store(), request, stage="rerank", candidates=candidates)
```

但 `RERANK_ENDPOINT` 未配置时，`reranker_from_settings()` 返回的是 `LexicalReranker`，它**只保序不重排**。此时 citations 里的 `score_stage=rerank` 是假标签。

### 影响

这是「hybrid 与 rrf 指标完全相同」的**根因之一**：报告显示跑的是精排，实际没跑，掩盖了「没有真重排」这个事实。如果不查，会在简历/答辩里说「做了精排」而被问穿。

### 修复

按真实状态标注：

```python
rerank_applied = not reranker.degraded and not isinstance(reranker, LexicalReranker)
actual_stage = "rerank" if rerank_applied else "rrf"
diagnostics["rerankApplied"] = rerank_applied   # 额外暴露给诊断
result = pipeline.recall(runtime.store(), request, stage=actual_stage, candidates=candidates)
```

修复后实测：`hybrid` 档位返回 `score_stage=rrf`，与事实一致。

### 注意

契约 `openapi-internal.yaml` 的 `score_stage` enum 是 `dense/sparse/rrf/rerank`，本次改动没有引入新值，契约兼容。

## 四、R3：chunk_size=180 未经调参（待定）

### 问题

`chunk_size=180` / `overlap=30` 是从 v1 继承的默认值。文档中的出处：

> `docs/02-重构设计/04_后端开发提示词.md:150`：`chunk_size=180` / `chunk_overlap=30`（v1 的 index.json 记录）

**没有任何调参实验记录**。同时实测切片长度分布为 min=113 / max=266 / mean=221——因为 `_trim_to_boundary` 允许回退 40%，实际长度会显著超出 180。

### 影响

面试若问「chunk_size 怎么定的」，只能回答「沿用默认值」。这是 RAG 项目最常被问的技术点之一。

### 建议

跑一次对比实验：`{120, 180, 240, 300}` × Recall@K，用现有评测脚本即可，产出「180 在 Recall@3 上最优」这类可复述结论。工作量约半小时。

## 五、代码质量亮点

审查中也确认了若干值得保留的设计：

| 位置 | 亮点 |
|---|---|
| `LexicalReranker` 注释 | 记录了 `a3_compare.py` 的实测：纯词项重排 3/6、加权 4/6、不重排 5/6 —— **用数据否决了自己的优化冲动** |
| `HttpReranker.rerank` | 分数饱和检测（极差 < 0.01 时退回保序），注释写明「照抄会把 top-1 从 5/6 打到 2/6」 |
| `HttpReranker.rerank` | 只信服务返回的 `index`，校验越界与重复，不信任任意新增字段 |
| `splitter._trim_to_boundary` | 回退幅度上限 40%，避免长句被切成碎片 |
| `splitter.split_section` | `step_floor` 防零步长死循环 |
| `splitter._POISON` | 指令注入检测，只降 `verified` 标记不删内容 |
| `iter_sections` | 标题路径逐级继承（`# A > ## B`），非固定占位串 |
| 全模块 | 纯函数无副作用，便于单测 |

## 六、修复后评测结果

修复 R1/R2 后重跑评测，指标**与修复前完全一致**：

| 档位 | R@1 | R@3 | R@5 | MRR | 漏检 |
|---|---|---|---|---|---|
| dense | 0.455 | 0.909 | 0.909 | 0.649 | 0 |
| bm25 | 0.636 | 0.818 | 1.000 | 0.758 | 0 |
| rrf | 0.727 | 1.000 | 1.000 | 0.833 | 0 |
| hybrid | 0.727 | 1.000 | 1.000 | 0.833 | 0 |

**这是正确结果**：修复只让标注符合事实，不改变检索行为。本批 11 道题未触发同分排序场景。

## 七、关于「精排无增益」的最终结论

三条证据链条完整：

1. `RERANK_ENDPOINT` 未配置 → 实际用的是 `LexicalReranker`（保序）
2. 保序意味着 `hybrid` 输出顺序 == `rrf` 输出顺序 → 指标必然相同
3. 修复 R2 后 `score_stage` 正确显示为 `rrf`，验证了上述推断

**结论**：本项目当前**没有做真正的模型精排**。若要在简历中声称「精排能力」，需要：
- 配置 `RERANK_ENDPOINT`（智谱/Jina rerank API）
- 或用本地 cross-encoder 模型（如 `bge-reranker-base`）
- 再跑一次评测验证增益

否则应表述为「RRF 融合 + 可插拔精排接口（未启用外部服务）」——这是诚实的说法。
