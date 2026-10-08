"""Serve the real frontend/backend against the existing isolated smoke database."""
import argparse
from contextlib import asynccontextmanager, nullcontext
from copy import deepcopy
import os
from pathlib import Path
import re

from sqlalchemy.engine import make_url

from scripts.bounded_cloud_meter import BoundedCloudMeter
from scripts.evaluate_comprehensive import load, save, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--budget', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=18085)
    p.add_argument('--replay-answers', type=Path, help='UI rendering/click verification of recorded real API answers; no new inference')
    a = p.parse_args()
    manifest = load(a.run_dir/'run_manifest.json')
    name = manifest['database_name']
    if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+', name):
        raise ValueError('Refusing production database')
    from backend.config import get_settings
    url = make_url(get_settings().DATABASE_URL).set(database=name)
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH'] = manifest['duckdb_path']
    os.environ['GRAPH_BUILD_ENABLED'] = 'false'
    get_settings.cache_clear()
    from backend.main import app
    from backend.routes import documents, query
    from backend.services import llm
    import uvicorn
    documents.UPLOAD_DIR = str(Path(manifest['duckdb_path']).parent/'uploads')
    if not Path(documents.UPLOAD_DIR).is_dir():
        raise ValueError('Isolated uploads missing')
    a.output.mkdir(parents=True, exist_ok=False)
    requests = []
    original_query = query.agent_query
    meter = BoundedCloudMeter(a.budget, a.output, max_new_attempts=None)
    replay = load(a.replay_answers) if a.replay_answers else None

    async def traced_query(question, session):
        meter.phase = {'stage': 'ui_answer', 'question': question}
        if replay is not None:
            matching = [row for row in replay if row.get('question') == question]
            if len(matching) != 1:
                raise ValueError('UI replay only permits an exactly recorded question')
            result, calls = deepcopy(matching[0]['full_result']), []
        else:
            with llm.trace_model_calls() as calls:
                result = await original_query(question, session)
        requests.append({'question': question, 'full_result': result, 'calls': calls})
        save(a.output/'ui_queries.json', requests)
        return result
    query.agent_query = traced_query
    async def isolated_qa_log(**entry):
        path = a.output/'qa_history.json'
        history = load(path) if path.exists() else []
        history.append(entry)
        save(path, history)
    query.save_qa_log = isolated_qa_log
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=a.port, log_level='warning'))

    @app.post('/__evaluation__/shutdown')
    async def shutdown():
        server.should_exit = True
        return {'stopping_isolated_server': True}

    save(a.output/'UI_RUN_STATE.json', {'pid': os.getpid(), 'port': a.port,
        'database_name': name, 'uploads': documents.UPLOAD_DIR,
        'duckdb_path': manifest['duckdb_path'], 'production_database_touched': False,
        'frontend': 'Unmodified repository frontend served by backend.main',
        'mode': 'recorded_API_answer_UI_replay' if replay is not None else 'fresh_UI_inference',
        'replay_answers_sha256': sha(a.replay_answers) if replay is not None else None,
        'sdk_attempts_added_at_start': 0})
    with (nullcontext() if replay is not None else meter):
        server.run()


if __name__ == '__main__':
    main()
