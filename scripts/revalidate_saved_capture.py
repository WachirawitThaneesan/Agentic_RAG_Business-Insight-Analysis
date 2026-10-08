"""Revalidate emitted raw generation with a new binder, preserving answer text.

Never infer annotations from a question/reference or reconstruct missing model
output. The original experiment stays untouched and the changed binder is a
rescore, not fresh generation or cloud validation.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from backend.services import answer_capture as capture
from scripts.evaluate_comprehensive import load, save, sha
from scripts.run_capture_paired import summarize


def run(source, output, labels_path=None):
    if output.exists():
        raise ValueError('Choose a new rescore output')
    output.mkdir(parents=True)
    records = load(source/'paired_answers.json')
    bank = load(source/'reference_locked.json')
    labels = load(labels_path or source/'numeric_labels_locked.json')
    lineage = []
    for row in records:
        for arm, record in row['arms'].items():
            full = record['full_result']
            old = deepcopy(full)
            cap = full.get('answer_capture', {})
            if not capture.validate_binding(full, record['answer']):
                raise ValueError('Original capture hash mismatch')
            event = None
            for call in reversed(record.get('model_calls', [])):
                if not isinstance(call.get('response'), str):
                    continue
                if capture.digest(call.get('prompt') or '') != cap.get('prompt_sha256'):
                    continue
                draft, payload = capture.decode(call['response'])
                if payload is None or capture.digest(draft) != cap.get('draft_sha256'):
                    continue
                event = dict(draft=draft, payload=payload, context=full['evidence_context'],
                    blocks=full['evidence_blocks'], prompt_sha256=cap['prompt_sha256'],
                    origin=cap['origin'])
                break
            if event:
                full = capture.finalize(full, [event])
                if full['answer'] != old['answer'] or full['answer_claims'] != old['answer_claims'] or full['claim_citations'] != old['claim_citations']:
                    raise ValueError('Rescore changed emitted prose, claims or links')
                record['full_result'] = full
            lineage.append(dict(id=row['id'], arm=arm, raw_generation_found=event is not None,
                answer_sha256=capture.digest(record['answer']), original_status=cap.get('status'),
                rescored_status=full['answer_capture']['status'], errors=full['answer_capture']['errors']))
    for name in ('reference_locked.json', 'numeric_labels_locked.json'):
        (output/name).write_bytes((source/name).read_bytes())
    if labels_path:
        (output/'numeric_labels_locked.json').write_bytes(labels_path.read_bytes())
    save(output/'paired_answers.json', records)
    arms = sorted({arm for row in records for arm in row['arms']})
    for arm in arms:
        save(output/(arm+'_answers.json'), [r['arms'][arm] for r in records if arm in r['arms']])
    save(output/'summary.json', summarize(records, labels, bank['documents'], len(records),
        planned_ids=[r['id'] for r in records], arms=arms,
        answerable_ids={q['id'] for q in bank['items'] if q['id'] in {r['id'] for r in records} and q.get('answerable', True)}))
    save(output/'lineage.json', dict(source=str(source.resolve()),
        original_answers_sha256=sha(source/'paired_answers.json'),
        numeric_labels_sha256=sha(labels_path or source/'numeric_labels_locked.json'),
        binder_sha256=sha(Path(capture.__file__)), sdk_attempts=0,
        method='raw-emitted-generation binder rescore; unchanged answer/claims/links', records=lineage))
    print('Revalidated', len(records), 'pairs; no new model calls')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--labels', type=Path)
    a = p.parse_args()
    run(a.source, a.output, a.labels)
