"""J5 batch comparison: contract, scoring, persistence and validation."""
import pytest
from conftest import wait_until

pytestmark = pytest.mark.live


def test_questions_cover_all_13_and_contract_types(api):
    questions = api('GET', '/eval/questions')
    assert [q['id'] for q in questions] == [f'T{i:02}' for i in range(1, 14)]
    assert {q['type'] for q in questions} == {'single', 'cross', 'out'}
    assert all(set(q) == {'id', 'type', 'question', 'keywords', 'evidence'} for q in questions)
    assert all(q['question'] and q['keywords'] for q in questions)


def test_full_batch_answers_scores_history_and_isolation(api, finished_run):
    before = api('GET', '/conversations')
    run = api('POST', '/eval/batch', json={'questionIds': [], 'mode': 'both', 'k': 3})
    result = finished_run(run['id'])
    assert result['progress'] == 100
    assert result['finishedAt'] >= result['createdAt']
    assert len(result['cases']) == 13
    assert result['stats']['total'] == 13
    assert result['stats']['passedRag'] > result['stats']['passedDirect']
    assert all(c['directAnswer'] and c['ragAnswer'] for c in result['cases'])
    assert all(isinstance(c['directPassed'], bool) and isinstance(c['ragPassed'], bool) for c in result['cases'])
    assert result['stats']['passedRag'] == sum(c['ragPassed'] for c in result['cases'])
    summaries = api('GET', '/eval/runs')
    summary = next(r for r in summaries if str(r['id']) == str(run['id']))
    assert 'cases' not in summary
    assert summary['stats'] == result['stats']
    assert api('GET', '/conversations') == before


def test_subset_and_k_are_preserved(api, finished_run):
    run = api('POST', '/eval/batch', json={'questionIds': ['T03', 'T09'], 'mode': 'both', 'k': 1})
    result = finished_run(run['id'])
    assert {c['questionId'] for c in result['cases']} == {'T03', 'T09'}
    assert result['k'] == 1
    assert all(len(c['ragSources']) <= 1 for c in result['cases'])


@pytest.mark.parametrize('payload', [
    None, {}, {'questionIds': [], 'mode': 'invalid', 'k': 3},
    {'questionIds': [], 'mode': 'both', 'k': 0},
    {'questionIds': [], 'mode': 'both', 'k': 11},
    {'questionIds': ['NO_SUCH_QUESTION'], 'mode': 'both', 'k': 3},
])
def test_invalid_batch_returns_400(java_client, payload):
    response = java_client.post('/api/v1/eval/batch', json=payload)
    assert response.status_code == 400, response.text
    assert response.json()['code'] // 100 == 400


def test_missing_run_returns_404(java_client):
    response = java_client.get('/api/v1/eval/runs/999999999')
    assert response.status_code == 404, response.text
