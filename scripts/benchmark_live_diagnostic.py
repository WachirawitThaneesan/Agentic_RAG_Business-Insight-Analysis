"""Repeat a frozen diagnostic against the configured, already ingested database.

Does not ingest, relabel, or overwrite results. Stop the API first if it owns
the same DuckDB file. Results are diagnostic, not an unseen-document claim.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
from scripts.experiment_meter import ExperimentMeter


async def run(manifest, meter):
    from backend.database import AsyncSessionLocal, engine
    from backend.services.agent import agent_query
    from backend.services.llm import usage, reset_usage
    from backend.eval.score_layers import score_answers
    predictions = {}; timings = []
    reset_usage()
    try:
        for item in manifest['items']:
            meter.phase.update(id=item['id'], arm='app_diagnostic')
            start = time.perf_counter(); before = dict(usage)
            try:
                async with AsyncSessionLocal() as db:
                    result = await asyncio.wait_for(agent_query(item['question_th'], db), 300)
            except Exception as exc:
                result = {'answer': '', 'sources': [], 'error_type': type(exc).__name__}
            predictions[item['id']] = {'id': item['id'], 'answer': result['answer'],
                'full_result': result, 'citations': [
                    {'filename': s['filename'], 'source_pdf_page': s['page']}
                    for s in result.get('sources', []) if s.get('filename') and s.get('page')]}
            timings.append({'id': item['id'], 'seconds': time.perf_counter()-start,
                            'usage': {k: usage[k]-before[k] for k in usage}})
            meter.save('progress.json', {'completed': len(predictions), 'predictions': predictions, 'timings': timings})
            print(f"Completed {len(predictions)}/{len(manifest['items'])}: {item['id']}", flush=True)
        scores = score_answers(manifest['items'], {d['code']:d for d in manifest['documents']}, predictions, page_space='source')
        scores['n_strict_supported_correct'] = sum(d['fact_status']=='correct' and d['all_required_pages_cited'] for d in scores['details'])
        meter.save('answers.json', list(predictions.values()))
        meter.save('metrics.json', {'scores': scores, 'usage': dict(usage), 'sdk_attempts': len(meter.calls), 'timings': timings})
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=False)
    meter = ExperimentMeter(args.output)
    meter.save('reference_locked.json', manifest)
    repo = Path(__file__).resolve().parents[1]
    meter.save('code_hashes.json', {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (repo/'backend').rglob('*.py')})
    meter.start()
    try:
        asyncio.run(run(manifest, meter))
    finally:
        meter.finish()


if __name__ == '__main__':
    main()
