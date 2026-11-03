import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2] / 'server-ai'))
from fastapi.testclient import TestClient
from app.main import app


def test_mock_stream_has_contract_events():
    r = TestClient(app).post('/internal/v1/chat/stream', headers={'X-Internal-Token':'dev-internal-token'}, json={'question':'借阅规则'})
    assert r.status_code == 200
    events=[]
    current=None
    for line in r.text.splitlines():
        if line.startswith('event: '): current=line[7:]
        elif line.startswith('data: '): events.append((current,json.loads(line[6:])))
    kinds=[e[0] for e in events]
    assert kinds[0:3] == ['status','status','status']
    assert 'retrieval' in kinds and 'token' in kinds and kinds[-1]=='done'
    done=events[-1][1]
    assert 'usage' in done and 'elapsed_ms' in done
