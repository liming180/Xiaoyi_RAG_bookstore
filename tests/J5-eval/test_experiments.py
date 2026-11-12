"""Experiment Cartesian groups, exclusion lock and durable metrics."""
import pytest
from conftest import read_sse

pytestmark = pytest.mark.live


def test_experiment_skips_invalid_overlap_and_blocks_conflicts(api, java_client, clean_db, finished_experiment):
    """笛卡尔展开 + 三把锁（40902 建实验 / 40901 聊天 / 恢复默认参数）。

    **为什么先上传一份资料**：本用例要在实验「正在跑」的窗口里断言 40902 与 40901，
    这个窗口得真的存在。空库时 `IndexServiceImpl.accept()` 走 `finishEmptyRebuild()`，
    建库瞬间成功 —— N4 之前这里靠「不问选题、每次都跑全部 13 题」凑出十几秒，接了
    `questionIds` 之后就只有 1 道题了，窗口缩到毫秒级，断言只能靠抢。放一份真资料进去，
    mock 档每次重建约 4 秒（`MockAiClient.getIngestTask` 按轮询次数推进），两组 ≈ 8 秒，
    窗口是稳的，而且这本来就是本用例真正想覆盖的路径（有片段要切、有向量要写）。
    """
    files = [
        (
            "files",
            (
                "j5_experiment.md",
                "# 借阅规则\n\n普通图书每人最多同时借阅 4 本，每本借期 21 天。\n\n续借一次增加 7 天。\n".encode(
                    "utf-8"
                ),
                "text/markdown",
            ),
        )
    ]
    uploaded = java_client.post("/api/v1/documents", files=files)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["data"]["accepted"], uploaded.text

    conv = api('POST', '/conversations', json={'title': 'experiment exclusion'})
    try:
        payload = {'name': 'J5 cartesian', 'questionIds': ['T03'], 'axes': {
            'chunkSize': [100, 200], 'overlap': [100], 'k': [1, 2],
            'rerank': [False], 'summary': [True],
        }}
        import time
        started = time.monotonic()
        experiment = api('POST', '/eval/experiments', json=payload)
        assert experiment['totalGroups'] == 2
        conflict = java_client.post('/api/v1/eval/experiments', json=payload)
        assert conflict.status_code == 409 and conflict.json()['code'] == 40902, conflict.text
        status, content_type, _, raw = read_sse({'conversationId': str(conv['id']), 'question': 'hello', 'mode': 'rag', 'k': 3})
        assert status == 409 and 'application/json' in content_type, raw
        import json
        assert json.loads(raw)['code'] == 40901
        result = finished_experiment(experiment['id'])
        # N1 之后每组都要先重建索引（本用例两组同参数，所以重建两次：首次对齐 200/100、
        # 收尾恢复 180/30），mock 档每次约 4 秒（MockAiClient 按轮询次数推进）。原来那条
        # 「< 5 秒」的前置条件已经不成立 —— 它写的时候实验根本不重建索引。
        # 这里换成一条宽松但仍有意义的上界：能失败的是「卡住」，不是「比 5 秒慢」。
        assert time.monotonic() - started < 90, '两组实验（含两次重建）应在 90 秒内跑完'
        assert result['finishedGroups'] == result['totalGroups'] == 2
        assert result['progress'] == 100
        report = api('GET', f"/eval/experiments/{experiment['id']}/report")
        assert report['experiment']['status'] == 'SUCCEEDED'
        assert len(report['runs']) == 2
        assert {r['params']['k'] for r in report['runs']} == {1, 2}
        assert all(r['params']['chunkSize'] == 200 and r['params']['overlap'] == 100 for r in report['runs'])
        for run in report['runs']:
            assert run['elapsedMs'] >= 0
            metrics = run['metrics']
            assert 0 <= metrics['hitRate'] <= 1
            assert metrics['avgElapsedMs'] >= 0 and metrics['failed'] == 0
            assert metrics['avgSources'] <= run['params']['k']
        # Finished jobs release the chat lock.
        status, _, events, raw = read_sse({'conversationId': str(conv['id']), 'question': 'hello', 'mode': 'direct', 'k': 1})
        assert status == 200 and any(e.event == 'done' for e in events), raw
    finally:
        api('DELETE', f"/conversations/{conv['id']}")


@pytest.mark.parametrize('axes,code', [
    ({'chunkSize': [100], 'overlap': [100, 200], 'k': [1], 'rerank': [True], 'summary': [False]}, 40004),
    ({'chunkSize': [], 'overlap': [0], 'k': [1], 'rerank': [True], 'summary': [False]}, 40004),
    # chunkSize 越界按契约回 40002（不是 40001），见 docs/api/error-codes.md 的编号分配说明。
    ({'chunkSize': [1], 'overlap': [0], 'k': [1], 'rerank': [True], 'summary': [False]}, 40002),
])
def test_invalid_experiment(java_client, axes, code):
    response = java_client.post('/api/v1/eval/experiments', json={'axes': axes, 'questionIds': ['T03']})
    assert response.status_code == 400, response.text
    assert response.json()['code'] == code, response.text


def test_missing_experiment(java_client):
    for path in ('/eval/experiments/999999999', '/eval/experiments/999999999/report'):
        response = java_client.get('/api/v1' + path)
        assert response.status_code == 404, response.text
