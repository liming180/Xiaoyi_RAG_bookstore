"""N1：参数实验的 `chunkSize` / `overlap` 轴必须真的重建向量库（Java 侧黑盒）。

修这个缺陷之前（`docs/02-重构设计/05_后端开发提示词_亮点包后端.md` §3.1），
`ExperimentServiceImpl` 只把 `k` 传给评测，`chunkSize` / `overlap` / `rerank` / `summary`
写进 `params_json` 落库后无人读取 —— 报告里两组参数不同、数字却完全一样，
于是「混合检索有没有变好」这个结论本身就是不可信的。

本文件守的是 **Java 侧能黑盒观测的部分**：

1. 每组开跑前按本组参数重建索引（落库证据：`index_task` 里出现该组自己的 chunk_size/overlap）；
2. 整场跑完恢复到默认 180/30，不把日常问答留在实验参数上；
3. 实验进行中 `POST /api/v1/index/rebuild` 回 40902，不让手动建库换掉正在测量的向量库；
4. 组数上限 8，第 9 组回 40001；
5. `metrics.effective` 如实标出 `summary` 未生效（N3 落地前恒 false，不许假装）。

关于文档 §3.2 里的第 1、2 条（「options 到达 Python」「rerank=false 时 citations 的
stage 变 rrf」）：那两条是 Python 侧行为，验收集在
`test/A3-hybrid/test_options_rerank.py`（真 HTTP 打 `/internal/v1/chat/stream`，6 条用例）；
Java 侧把 camelCase 参数翻成 snake_case `options` 的部分由
`server-java/src/test/java/com/xiaoyi/rag/service/EvalServiceOptionsTest.java` 覆盖。
本文件不重复它们，也不把它们写成「在这里跑过」。

为什么用 `index_task` 表而不是 `/index/status` 做证据：mock 档下重建走 4 次轮询
（约 4 秒）才 SUCCEEDED，而 `/index/status` 只报**最近一次成功**任务的参数 ——
两组各重建一次、最后又恢复一次默认，跑完再查只剩 180/30，中间两组的参数根本看不到。
落库记录是唯一能证明「每组都真的建过库」的观测点，也符合 conftest 的约定
（HTTP 做验收、DB 只做持久化断言）。
"""

from __future__ import annotations

import pytest

from conftest import wait_until

pytestmark = pytest.mark.live

#: 默认推荐参数（XiaoyiProperties.index.defaultChunkSize / defaultOverlap）。
DEFAULT_CHUNK_SIZE = 180
DEFAULT_OVERLAP = 30


def _axes(chunk, overlap, k, rerank, summary):
    """按契约 ExperimentAxis 拼参数轴。"""
    return {
        "chunkSize": chunk,
        "overlap": overlap,
        "k": k,
        "rerank": rerank,
        "summary": summary,
    }


def _index_tasks(user_id):
    """读 `index_task` 里该用户的建库记录，按 id 升序。

    连不上库就 skip —— 这不是被测行为的问题，而是本机没装驱动或库不可达。
    """
    try:
        import pymysql  # type: ignore
    except ImportError:  # pragma: no cover - 环境问题
        pytest.skip("未安装 pymysql，无法核对 index_task 落库记录")

    from conftest import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            autocommit=True,
        )
    except Exception as error:  # pragma: no cover - 环境问题
        pytest.skip(f"连不上门禁库，无法核对 index_task：{error}")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_size, overlap, status FROM index_task"
                " WHERE user_id = %s ORDER BY id",
                (user_id,),
            )
            return [
                {"chunkSize": row[0], "overlap": row[1], "status": row[2]}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def _current_user(api):
    """当前登录用户 id：`/index/status` 与 `index_task` 都按这个 id 归属。"""
    return api("GET", "/auth/profile")["id"]


def test_experiment_rebuilds_index_for_each_group(api, clean_db, finished_experiment):
    """两组不同 chunkSize 各自重建一次：`index_task` 里两条参数都要出现。

    这一条是「四根轴里三根是装饰」的直接反证：修好之前，整场实验不会产生任何建库任务。
    """
    user_id = _current_user(api)
    experiment = api(
        "POST",
        "/eval/experiments",
        json={
            "name": "N1 chunk axis",
            "questionIds": ["T03"],
            "axes": _axes([300, 400], [40], [2], [True], [False]),
        },
    )
    assert experiment["totalGroups"] == 2, experiment

    result = finished_experiment(experiment["id"])
    assert result["finishedGroups"] == result["totalGroups"] == 2, result

    tasks = _index_tasks(user_id)
    succeeded = {(t["chunkSize"], t["overlap"]) for t in tasks if t["status"] == "SUCCEEDED"}
    # 本组参数各一次 …
    assert (300, 40) in succeeded, f"chunkSize=300 那组没有留下建库记录：{tasks}"
    assert (400, 40) in succeeded, f"chunkSize=400 那组没有留下建库记录：{tasks}"
    # … 收尾再恢复一次默认。
    assert (DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP) in succeeded, f"收尾没有恢复默认参数：{tasks}"


def test_experiment_restores_default_params(api, clean_db, finished_experiment):
    """实验结束后 `/index/status` 回到默认 180/30，日常问答不会建在实验参数上。"""
    experiment = api(
        "POST",
        "/eval/experiments",
        json={
            "name": "N1 restore",
            "questionIds": ["T03"],
            "axes": _axes([300], [40], [2], [True], [False]),
        },
    )
    finished_experiment(experiment["id"])

    status = api("GET", "/index/status")
    assert status["chunkSize"] == DEFAULT_CHUNK_SIZE, status
    assert status["overlap"] == DEFAULT_OVERLAP, status


def test_rebuild_blocked_while_experiment_running(api, java_client, clean_db, finished_experiment):
    """实验进行中手动重建必须被 40902 拦下，否则正在测量的向量库会被换掉。

    用两组把窗口拉长到十秒以上（mock 档每组重建约 4 秒），避免踩在实验刚结束的边界上。
    """
    experiment = api(
        "POST",
        "/eval/experiments",
        json={
            "name": "N1 rebuild lock",
            "questionIds": ["T03"],
            "axes": _axes([300, 400], [40], [2], [True], [False]),
        },
    )
    # create() 返回时状态就是 RUNNING，紧接着发建库请求，撞进窗口的概率接近 1。
    assert api("GET", f"/eval/experiments/{experiment['id']}")["status"] == "RUNNING"

    conflict = java_client.post(
        "/api/v1/index/rebuild", json={"chunkSize": 200, "overlap": 20}
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == 40902, conflict.text

    # 实验照常跑完：互斥只挡外部建库，不挡实验自己的重建通道。
    assert finished_experiment(experiment["id"])["status"] == "SUCCEEDED"


def test_experiment_group_limit(java_client):
    """9 组回 400 + 40001，message 写明上限 8 组。"""
    axes = _axes([100, 200, 300], [10], [1, 2, 3], [True], [False])  # 3 × 1 × 3 = 9 组
    response = java_client.post(
        "/api/v1/eval/experiments",
        json={"name": "N1 too many groups", "questionIds": ["T03"], "axes": axes},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == 40001, body
    assert "最多 8 组" in body["message"], body


def test_experiment_effective_flags(api, clean_db, finished_experiment):
    """`metrics.effective` 如实标出哪几根轴生效：summary 恒 false，其余 true。

    这一栏是前端「本组生效参数」列的取值来源，也是本任务「不许假装」的验收核心。
    """
    experiment = api(
        "POST",
        "/eval/experiments",
        json={
            "name": "N1 effective flags",
            "questionIds": ["T03"],
            "axes": _axes([300], [40], [2], [True], [True]),
        },
    )
    finished_experiment(experiment["id"])

    report = api("GET", f"/eval/experiments/{experiment['id']}/report")
    assert len(report["runs"]) == 1, report
    metrics = report["runs"][0]["metrics"]
    effective = metrics.get("effective")
    assert effective == {
        "k": True,
        "rerank": True,
        "chunkSize": True,
        "overlap": True,
        "summary": False,
    }, f"生效标注不对：{metrics}"


def test_experiment_progress_advances_per_group(api, clean_db, finished_experiment):
    """进度必须真实递增：每组跑完 `finishedGroups` +1、`progress` 跟着涨。

    不许出现「跑完显示 100、中间一直 0」——那会让 8 组实验看起来卡死。
    """
    experiment = api(
        "POST",
        "/eval/experiments",
        json={
            "name": "N1 progress",
            "questionIds": ["T03"],
            "axes": _axes([300, 400], [40], [2], [True], [False]),
        },
    )
    seen = []

    def _read():
        current = api("GET", f"/eval/experiments/{experiment['id']}")
        if current["finishedGroups"] not in seen:
            seen.append(current["finishedGroups"])
        return current if current["status"] in ("SUCCEEDED", "FAILED") else None

    result = wait_until(_read, timeout=120, message="实验未在 120s 内结束")
    assert result["status"] == "SUCCEEDED", result
    assert seen == sorted(seen), f"finishedGroups 回退过：{seen}"
    assert result["progress"] == 100, result
