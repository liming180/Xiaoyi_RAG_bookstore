"""Experiment Cartesian groups, exclusion lock and durable metrics."""
import pytest
from conftest import read_sse

pytestmark = pytest.mark.live


def test_experiment_skips_invalid_overlap_and_blocks_conflicts(api, java_client, finished_experiment):
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
        assert time.monotonic() - started < 5, 'two experiment groups must finish within five seconds with mock AI'
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
    ({'chunkSize': [1], 'overlap': [0], 'k': [1], 'rerank': [True], 'summary': [False]}, 40001),
])
def test_invalid_experiment(java_client, axes, code):
    response = java_client.post('/api/v1/eval/experiments', json={'axes': axes, 'questionIds': ['T03']})
    assert response.status_code == 400, response.text
    assert response.json()['code'] == code, response.text


def test_missing_experiment(java_client):
    for path in ('/eval/experiments/999999999', '/eval/experiments/999999999/report'):
        response = java_client.get('/api/v1' + path)
        assert response.status_code == 404, response.text
