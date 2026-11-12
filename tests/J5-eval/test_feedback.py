"""Feedback upsert and candidate decisions are durable business records."""
import pytest

pytestmark = pytest.mark.live


def test_feedback_up_down_summary_and_candidate(api, assistant):
    question = 'J5候选问题：普通图书最多同时借阅几本借多久？'
    mid = assistant(question)
    before = api('GET', '/feedback/summary')
    api('POST', f'/messages/{mid}/feedback', json={'rating': 'up', 'tags': ['准确'], 'comment': '清楚'})
    up = api('GET', '/feedback/summary')
    assert up['total'] == before['total'] + 1
    assert up['up'] == before['up'] + 1
    api('POST', f'/messages/{mid}/feedback', json={'rating': 'down', 'tags': ['来源不足'], 'comment': '补充依据'})
    down = api('GET', '/feedback/summary')
    assert down['total'] == up['total']
    assert down['down'] == before['down'] + 1
    assert down['up'] == before['up']
    candidates = api('GET', '/eval/candidates')
    candidate = next(c for c in candidates if c['question'] == question)
    assert candidate['source'] == 'feedback' and candidate['status'] == 'pending'
    api('POST', f'/messages/{mid}/feedback', json={'rating': 'down', 'tags': [], 'comment': ''})
    assert len(api('GET', '/eval/candidates')) == len(candidates)
    api('POST', f"/eval/candidates/{candidate['id']}/decision", json={'status': 'accepted'})
    assert next(c for c in api('GET', '/eval/candidates') if c['id'] == candidate['id'])['status'] == 'accepted'
    assert api('GET', '/feedback/summary')['candidates'] == down['candidates'] - 1


def test_ignore_candidate(api, assistant):
    question = 'J5忽略候选：如何借书？'
    mid = assistant(question)
    api('POST', f'/messages/{mid}/feedback', json={'rating': 'down'})
    candidate = next(c for c in api('GET', '/eval/candidates') if c['question'] == question)
    api('POST', f"/eval/candidates/{candidate['id']}/decision", json={'status': 'ignored'})
    assert next(c for c in api('GET', '/eval/candidates') if c['id'] == candidate['id'])['status'] == 'ignored'


@pytest.mark.parametrize('path,body,expected', [
    ('/messages/999999999/feedback', {'rating': 'up'}, 404),
    ('/messages/999999999/feedback', {'rating': 'other'}, 400),
    ('/eval/candidates/999999999/decision', {'status': 'accepted'}, 404),
    ('/eval/candidates/999999999/decision', {'status': 'pending'}, 400),
])
def test_feedback_failures(java_client, path, body, expected):
    response = java_client.post('/api/v1' + path, json=body)
    assert response.status_code == expected, response.text
