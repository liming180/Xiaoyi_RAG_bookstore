import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / 'server-ai'))
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = {'X-Internal-Token': 'dev-internal-token'}
ROUTES = [
    ('get', '/internal/v1/health', None),
    ('get', '/internal/v1/index/status', None),
    ('post', '/internal/v1/retrieve', {}),
    ('post', '/internal/v1/eval/batch', {'cases': [{'id': 'T1', 'question': 'q', 'keywords': 'x'}], 'mode': 'both', 'k': 1}),
    ('post', '/internal/v1/documents/parse', {'documents': [{'doc_id': 'd1', 'name': 'a.md', 'text': 'hello'}], 'chunk_size': 180, 'overlap': 30}),
]


def test_all_envelope_routes_authorized():
    for method, path, body in ROUTES:
        response = getattr(client, method)(path, headers=TOKEN, json=body) if body is not None else getattr(client, method)(path, headers=TOKEN)
        assert response.status_code == 200, (path, response.text)
        assert set(response.json()) == {'code', 'message', 'data', 'timestamp'}


def test_chat_stream_authorized():
    response = client.post('/internal/v1/chat/stream', headers=TOKEN, json={'question': 'q'})
    assert response.status_code == 200
    assert 'event: done' in response.text


def test_missing_token_is_401():
    response = client.get('/internal/v1/health')
    assert response.status_code == 401 and response.json()['code'] == 40102


def test_unknown_task_and_document_are_404():
    task = client.get('/internal/v1/ingest/missing', headers=TOKEN)
    assert task.status_code == 404 and task.json()['code'] == 40402
    document = client.get('/internal/v1/documents/missing/status', headers=TOKEN)
    assert document.status_code == 404 and document.json()['code'] == 40401


def test_validation_error_uses_envelope():
    response = client.post('/internal/v1/documents/parse', headers=TOKEN, json={})
    assert response.status_code == 400
    assert set(response.json()) == {'code', 'message', 'data', 'timestamp'}
    assert response.json()['code'] == 40001
