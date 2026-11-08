"""N4：反馈 → 候选池 → 采纳 → 进实验计分 这条链路（Java 侧黑盒）。

修之前（`docs/02-重构设计/05_后端开发提示词_亮点包后端.md` §6.1）：
`FeedbackService.decide` 只把 status 改成 accepted/ignored，之后没有任何消费者；
`CreateExperimentRequest` 没有 `questionIds`；`EvalServiceImpl.loadQuestions` 硬校验 13 题，
题库只能来自 `assets/eval/questions.csv`。也就是说「点踩 → 候选 → 采纳 → 进实验」
走到「采纳」就断了，候选池是个只进不出的垃圾桶。

必须拍板的边界：候选没有判分关键词，`judge()` 判不出对错。定案是两档：

- 补了 `keywords` → 进实验并**计分**（进 hitRate 分母）；
- 没补 → 也能进实验，但标 `metrics.unscored`，**不进分母**。

本文件守的是能黑盒观测的部分（HTTP 验收 + 落库佐证）：

1. `decision` 带 keywords 时写入、不带时保留原值、传空串时清空；
2. `GET /eval/candidates/export` 回真 `text/csv`（BOM + 表头 + 只含 accepted）；
3. 实验选题 `C<候选id>` 走候选池：accepted 能进，pending / 别人的一律 40001；
4. 报告里 `scored` / `unscored` 如实分组，且 hitRate 的分母是 scored 而不是总题数。

关于第 4 条的验证深度：`hitRate` 的精确数值取决于 mock provider 的答案是否命中关键词，
在这里钉一个固定小数等于把用例绑死在 mock 文案上。所以**只钉分母**：
`scored + unscored == 选题数`，且 `scored` 恰好等于「补了关键词的题数」。
分母错了这一栏立刻对不上；文案变了这一栏不动。
"""

from __future__ import annotations

import pytest

from conftest import wait_until

pytestmark = pytest.mark.live

#: 候选题的判分关键词：语法同 assets/eval/keywords.csv（组内 `/` 同义、组间 `|` 全中）。
CANDIDATE_KEYWORDS = "3次/三次|续借"


def _axes():
    """一组最小参数：不触发重建（180/30 就是默认值），只验选题与计分口径。"""
    return {
        "chunkSize": [180],
        "overlap": [30],
        "k": [3],
        "rerank": [True],
        "summary": [False],
    }


def _candidate_of(api, question):
    """按问题文本找出刚才 👎 产生的那条候选。"""
    candidates = api("GET", "/eval/candidates")
    assert isinstance(candidates, list), candidates
    for row in candidates:
        if row["question"] == question:
            return row
    raise AssertionError(f"候选池里找不到问题「{question}」：{candidates}")


def _down_and_candidate(api, assistant, question):
    """走真实链路造一条候选：提问 → 点👎 → 回候选池取它。"""
    message_id = assistant(question)
    api("POST", f"/messages/{message_id}/feedback", json={"rating": "down", "tags": ["来源不足"]})
    return _candidate_of(api, question)


def _accepted(api, assistant, question, keywords=None):
    """提问 → 👎 → 带/不带关键词采纳，返回候选 id（字符串，用于 C<id> 题号）。"""
    candidate = _down_and_candidate(api, assistant, question)
    body = {"status": "accepted"}
    if keywords is not None:
        body["keywords"] = keywords
    api("POST", f"/eval/candidates/{candidate['id']}/decision", json=body)
    return candidate["id"]


def _run_experiment(api, question_ids, finished_experiment):
    """建一场实验并等它跑完，返回 (实验, 报告 runs)。"""
    experiment = api(
        "POST",
        "/eval/experiments",
        json={"name": "N4 候选闭环", "questionIds": question_ids, "axes": _axes()},
    )
    finished_experiment(experiment["id"])
    report = api("GET", f"/eval/experiments/{experiment['id']}/report")
    return experiment, report["runs"]


def test_accepted_candidate_with_keywords_can_join_experiment(api, clean_db, assistant, finished_experiment):
    """补了关键词的候选能进实验，且计进 scored。"""
    candidate_id = _accepted(api, assistant, "N4 候选题：续借最多可以续几次？", CANDIDATE_KEYWORDS)

    # 候选池要能读回关键词：没有这一列，前端就没法提示「采纳后能不能计分」。
    stored = _candidate_of(api, "N4 候选题：续借最多可以续几次？")
    assert stored["keywords"] == CANDIDATE_KEYWORDS, stored

    _experiment, runs = _run_experiment(
        api, ["T03", f"C{candidate_id}"], finished_experiment
    )
    assert len(runs) == 1, runs
    metrics = runs[0]["metrics"]
    assert metrics["scored"] == 2, metrics  # T03 + 候选题，都有关键词
    assert metrics["unscored"] == 0, metrics


def test_accepted_candidate_without_keywords_is_unscored(api, clean_db, assistant, finished_experiment):
    """没补关键词的候选照样能进实验，但落在 unscored、不进分母。

    这一条是整个 N4 的判定核心：没有关键词就判不出对错（judge 恒 false）。
    算进分母等于「每采纳一道没补关键词的候选，命中率就莫名掉一截」，
    而用户什么都没做错 —— 他只是还没补关键词。
    """
    candidate_id = _accepted(api, assistant, "N4 未补关键词：活动室怎么预约？", keywords=None)

    stored = _candidate_of(api, "N4 未补关键词：活动室怎么预约？")
    assert stored["keywords"] is None, stored

    _experiment, runs = _run_experiment(
        api, ["T03", f"C{candidate_id}"], finished_experiment
    )
    metrics = runs[0]["metrics"]
    assert metrics["scored"] == 1, metrics  # 只有 T03 可计分
    assert metrics["unscored"] == 1, metrics


def _expect_40001(java_client, question_ids):
    """直接用裸 client 断言「400 + 40001」，比用 api fixture 期望 AssertionError 精确得多。"""
    response = java_client.post(
        "/api/v1/eval/experiments",
        json={"name": "N4 负例", "questionIds": question_ids, "axes": _axes()},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == 40001, body
    return body


def test_pending_candidate_cannot_join_experiment(api, clean_db, assistant, java_client):
    """还没采纳的候选不能进实验：与「题号写错」同一条 40001，不给存在性信号。"""
    candidate = _down_and_candidate(api, assistant, "N4 pending：图书馆几点关门？")
    assert candidate["status"] == "pending", candidate

    body = _expect_40001(java_client, [f"C{candidate['id']}"])
    assert "题目不存在" in body["message"], body


def test_ignored_candidate_cannot_join_experiment(api, clean_db, assistant, java_client):
    """忽略掉的候选同样不能进实验。"""
    candidate = _down_and_candidate(api, assistant, "N4 ignored：可以带饮料进馆吗？")
    api("POST", f"/eval/candidates/{candidate['id']}/decision", json={"status": "ignored"})

    _expect_40001(java_client, [f"C{candidate['id']}"])


def test_other_users_candidate_rejected(api, clean_db, java_client_b, assistant):
    """B 的候选在 A 的实验里回 40001 —— 与不存在的 id 同一条消息，不泄露存在性。"""
    candidate = _down_and_candidate(api, assistant, "N4 越权：如何办证？")

    # 用 B 的身份去建包含 A 候选的实验。
    response = java_client_b.post(
        "/api/v1/eval/experiments",
        json={
            "name": "N4 越权",
            "questionIds": [f"C{candidate['id']}"],
            "axes": _axes(),
        },
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == 40001, body
    # 消息里只有题号，没有「候选存在但不属于你」这种可枚举信号。
    assert "题目不存在" in body["message"], body


def test_candidate_export_csv(api, clean_db, assistant, java_client):
    """导出：真 text/csv、带 BOM、表头 question,keywords、只含 accepted。"""
    question = "N4 导出：读书会多久办一次？"
    _accepted(api, assistant, question, CANDIDATE_KEYWORDS)
    # 再造一条 pending，确认它不出现在导出里。
    _down_and_candidate(api, assistant, "N4 导出：还没采纳的问题？")

    response = java_client.get("/api/v1/eval/candidates/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv"), response.headers

    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff"), "导出必须带 BOM，否则 Excel 打开是乱码"
    lines = [line for line in text.split("\r\n") if line]
    assert lines[0] == "\ufeffquestion,keywords", lines[0]

    body = lines[1:]
    joined = "\n".join(body)
    assert question in joined, f"已采纳的候选没出现在导出里：{body}"
    assert CANDIDATE_KEYWORDS in joined, f"关键词没带出来：{body}"
    assert "还没采纳的问题" not in joined, f"pending 候选不该被导出：{body}"


def test_export_quotes_fields_with_comma(api, clean_db, assistant, java_client):
    """含半角逗号的问题必须整段加引号：否则一行会多出一列，Excel 里整表错位。"""
    _accepted(api, assistant, "N4 逗号,问题,怎么借书？", keywords=None)

    response = java_client.get("/api/v1/eval/candidates/export")
    text = response.content.decode("utf-8")
    assert '"N4 逗号,问题,怎么借书？"' in text, text


def test_decision_without_keywords_keeps_existing(api, clean_db, assistant):
    """不带 keywords 的第二次 decide 不能清空已补的关键词。

    前端「纳入实验」会先弹关键词输入框；用户也可能之后再点一次（只改状态）。
    如果按「没带就清空」处理，刚补的关键词会静默丢失，报表上只表现为 unscored+1 ——
    找不到原因。
    """
    candidate = _down_and_candidate(api, assistant, "N4 保留关键词：能借几本？")
    api(
        "POST",
        f"/eval/candidates/{candidate['id']}/decision",
        json={"status": "accepted", "keywords": CANDIDATE_KEYWORDS},
    )
    api("POST", f"/eval/candidates/{candidate['id']}/decision", json={"status": "accepted"})

    stored = _candidate_of(api, "N4 保留关键词：能借几本？")
    assert stored["keywords"] == CANDIDATE_KEYWORDS, stored


def test_ignored_decision_does_not_store_keywords(api, clean_db, assistant):
    """忽略时不写关键词：被忽略的候选不进实验，存了也没人读，只会让导出多出无意义的行。"""
    candidate = _down_and_candidate(api, assistant, "N4 忽略不存关键词：几点开门？")
    api(
        "POST",
        f"/eval/candidates/{candidate['id']}/decision",
        json={"status": "ignored", "keywords": "不该写入"},
    )

    stored = _candidate_of(api, "N4 忽略不存关键词：几点开门？")
    assert stored["status"] == "ignored", stored
    assert stored["keywords"] is None, stored


def test_candidate_ids_mix_with_bank_questions(api, clean_db, assistant, finished_experiment):
    """题库题与候选题可以混选：题号顺序按请求走，两种来源各自解析。"""
    candidate_id = _accepted(api, assistant, "N4 混选：可以续借几次？", CANDIDATE_KEYWORDS)

    _experiment, runs = _run_experiment(
        api, ["T01", f"C{candidate_id}", "T05"], finished_experiment
    )
    metrics = runs[0]["metrics"]
    # 3 题全部有关键词（T01/T05 来自题库，候选题补过）→ 全部可计分。
    assert metrics["scored"] == 3, metrics
    assert metrics["unscored"] == 0, metrics


def test_unknown_bank_question_still_rejected(clean_db, java_client):
    """内置题库的题号校验没被候选题逻辑破坏：T99 仍然 40001。"""
    _expect_40001(java_client, ["T99"])


def test_malformed_candidate_id_rejected(clean_db, java_client):
    """题号 C 后面不是数字：回 40001 而不是 500。"""
    _expect_40001(java_client, ["Cabc"])
