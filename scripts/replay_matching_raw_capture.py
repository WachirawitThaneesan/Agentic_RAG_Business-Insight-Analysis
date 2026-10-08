"""Offline capture repair over exact emitted drafts; original output is immutable."""
import argparse
from copy import deepcopy
from pathlib import Path

from backend.services import answer_capture as capture
from scripts.evaluate_comprehensive import load, save, sha
from scripts.run_capture_paired import summarize


def replay(a):
    if a.output.exists():
        raise ValueError('Use a new derived evidence directory')
    records = load(a.source/'paired_answers.json')
    bank = load(a.source/'reference_locked.json')
    labels = load(a.source/'numeric_labels_locked.json')
    lineage = []
    for row in records:
        for arm, out in row['arms'].items():
            old = deepcopy(out['full_result'])
            cap = old.get('answer_capture', {})
            event = None
            if capture.validate_binding(old, out['answer']):
                for call in reversed(out.get('model_calls', [])):
                    if capture.digest(call.get('prompt') or '') != cap.get('prompt_sha256'):
                        continue
                    draft, data = capture.decode(call.get('response') or '')
                    if data is None or capture.digest(draft) != cap.get('draft_sha256'):
                        continue
                    event = dict(draft=draft, payload=data, context=old['evidence_context'],
                        blocks=old['evidence_blocks'], prompt_sha256=cap['prompt_sha256'], origin=cap['origin'])
                    break
            revised = capture.finalize(old, [event]) if event else old
            if (revised.get('answer') != old.get('answer')
                    or revised.get('answer_claims') != old.get('answer_claims')
                    or revised.get('claim_citations') != old.get('claim_citations')):
                revised = old
                event = None
            out['full_result'] = revised
            lineage.append(dict(id=row['id'], arm=arm, exact_raw_event_found=event is not None,
                original_status=cap.get('status'), new_status=revised.get('answer_capture', {}).get('status'),
                original_errors=cap.get('errors'), new_errors=revised.get('answer_capture', {}).get('errors')))
    save(a.output/'paired_answers.json', records)
    for name in ('reference_locked.json', 'numeric_labels_locked.json'):
        target = a.output/name
        target.write_bytes((a.source/name).read_bytes())
    arms = sorted({arm for row in records for arm in row['arms']})
    for arm in arms:
        save(a.output/(arm+'_answers.json'), [row['arms'][arm] for row in records])
    summary = summarize(records, labels, bank['documents'], len(records),
        planned_ids=[row['id'] for row in records], arms=arms,
        answerable_ids={q['id'] for q in bank['items'] if q.get('answerable', True)})
    save(a.output/'summary.json', summary)
    save(a.output/'lineage.json', dict(source=str(a.source), source_sha256=sha(a.source/'paired_answers.json'),
        binder_sha256=sha(capture.__file__), sdk_attempts=0, scope='Offline binding-only repair, not new generation or new live accuracy',
        answer_claims_links_unchanged=True, gold_scorer_unchanged=True, records=lineage))
    print(dict(n_outputs=len(records), raw_matches=sum(r['exact_raw_event_found'] for r in lineage),
        recovered=sum(r['original_status'] != 'captured' and r['new_status'] == 'captured' for r in lineage),
        regressed=sum(r['original_status'] == 'captured' and r['new_status'] != 'captured' for r in lineage),
        new_sdk_attempts=0))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    replay(p.parse_args())
