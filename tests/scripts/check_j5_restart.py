"""Explicit restart probe for local gate service (not part of ordinary pytest).

Run only against the test instance started by serve_java.py. Inserts interrupted
records, restarts that PID, then checks durable results and lock release.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from conftest import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, BASE_JAVA, JAVA_TOKEN
import pymysql
import httpx


def main():
    with httpx.Client(base_url=BASE_JAVA, headers={'Authorization': f'Bearer {JAVA_TOKEN}'}) as client:
        existing_runs = client.get('/api/v1/eval/runs').json()['data']
        previous = next((r for r in existing_runs if r['status'] == 'SUCCEEDED'), None)
        assert previous, 'run J5 tests first to create a completed durable run'
        detail = client.get(f"/api/v1/eval/runs/{previous['id']}").json()['data']
    connection = pymysql.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER,
                                 password=DB_PASSWORD, database=DB_NAME, autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO eval_run(name,mode,top_k,question_count,status,progress,created_at) VALUES('restart probe','both',3,13,'RUNNING',10,UNIX_TIMESTAMP())")
        run_id = cursor.lastrowid
        cursor.execute("INSERT INTO experiment(name,status,progress,total_groups,finished_groups,created_at,axes_json) VALUES('restart probe','RUNNING',0,1,0,UNIX_TIMESTAMP(),'{}')")
        experiment_id = cursor.lastrowid
    # serve_java may be a Java launcher with a child JVM; stop the full JVM set
    # so the packaged jar cannot remain alive behind the launcher process.
    subprocess.run(['taskkill', '/IM', 'java.exe', '/F'], check=False, capture_output=True)
    subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'test/scripts/serve_java.py'), '--detach', '--profile', 'gate-probe'], cwd=ROOT, check=True)
    with httpx.Client(base_url=BASE_JAVA, headers={'Authorization': f'Bearer {JAVA_TOKEN}'}) as client:
        recovered = client.get(f'/api/v1/eval/runs/{run_id}').json()['data']
        experiment = client.get(f'/api/v1/eval/experiments/{experiment_id}').json()['data']
        persisted = client.get(f"/api/v1/eval/runs/{previous['id']}").json()['data']
        assert recovered['status'] == 'FAILED' and recovered['finishedAt']
        assert experiment['status'] == 'FAILED' and experiment['finishedAt']
        assert persisted == detail
    connection.close()
    print(json.dumps({'restartRecovery': True, 'completedRunPreserved': True, 'evalRunId': run_id, 'experimentId': experiment_id}))


if __name__ == '__main__':
    main()
