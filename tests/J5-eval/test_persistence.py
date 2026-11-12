"""Check durable eval result/CSV and feedback tags against MySQL."""
import csv
import io
import json
import pytest
from conftest import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

pytestmark = pytest.mark.live


@pytest.fixture
def db():
    pymysql = pytest.importorskip('pymysql')
    connection = pymysql.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER,
                                 password=DB_PASSWORD, database=DB_NAME,
                                 cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    yield connection
    connection.close()


def test_finished_run_has_durable_cases_stats_and_bom_csv(api, finished_run, db):
    run = api('POST', '/eval/batch', json={'questionIds': ['T03', 'T09'], 'mode': 'both', 'k': 2})
    result = finished_run(run['id'])
    with db.cursor() as cursor:
        cursor.execute('SELECT * FROM eval_run WHERE id=%s', (run['id'],))
        row = cursor.fetchone()
    assert row and row['status'] == 'SUCCEEDED'
    raw = row['result_csv']
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    assert raw.startswith('\ufeff')
    rows = list(csv.reader(io.StringIO(raw.lstrip('\ufeff'))))
    assert rows[0] == ['题号', '题型', '问题', '不查资料回答', '不查资料初判', '查资料回答', '查资料初判', '来源数', '耗时(ms)']
    assert len(rows) == 3
    assert [r[0] for r in rows[1:]] == [c['questionId'] for c in result['cases']]
    assert all(r[1] in ('单文档', '跨文档', '库外') and r[4] in ('通过', '未通过') for r in rows[1:])


def test_feedback_preserves_tags_comment_and_current_rating(api, assistant, db):
    mid = assistant('J5持久化反馈对应问题')
    api('POST', f'/messages/{mid}/feedback', json={'rating': 'down', 'tags': ['缺少证据', '不完整'], 'comment': '需要更明确的出处'})
    with db.cursor() as cursor:
        cursor.execute('SELECT rating,tags_json,comment FROM feedback WHERE message_id=%s', (mid,))
        row = cursor.fetchone()
        cursor.execute('SELECT question FROM eval_candidate WHERE message_id=%s', (mid,))
        candidate = cursor.fetchone()
    assert row['rating'] == 'down'
    assert json.loads(row['tags_json']) == ['缺少证据', '不完整']
    assert row['comment'] == '需要更明确的出处'
    assert candidate['question'] == 'J5持久化反馈对应问题'
