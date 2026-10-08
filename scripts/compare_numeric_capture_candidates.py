"""Compare every required numeric relation, retaining omissions and regressions."""
import argparse
from collections import Counter
from pathlib import Path

from backend.eval.contract_replay import numeric_results
from backend.services.answer_capture import validate_binding
from scripts.evaluate_comprehensive import load, save, sha


def compare(a):
    baseline = load(a.baseline/'paired_answers.json')
    candidate = load(a.candidate/'paired_answers.json')
    labels = load(a.baseline/'numeric_labels_locked.json')
    bank = load(a.baseline/'reference_locked.json')
    manifest = load(a.candidate/'manifest.json')
    required_ids = {n['id'] for n in labels}
    ids = [r['id'] for r in candidate]
    if len(labels) != 102 or len(required_ids) != 94 or ids != manifest['selected_ids'] or not required_ids <= set(ids):
        raise ValueError('Candidate must complete every selected question and all94 numeric questions /102 relations')
    for f in ('reference_locked.json', 'numeric_labels_locked.json'):
        if sha(a.baseline/f) != sha(a.candidate/f):
            raise ValueError('Reference/scorer comparison inputs differ')
    for f, digest in manifest['code_sha256'].items():
        if sha(a.candidate/'frozen_code'/f) != digest:
            raise ValueError('Frozen candidate code changed: '+f)
    previous = {r['id']: r for r in baseline}
    rows = []
    capture_rows = []
    for row in candidate:
        qid = row['id']
        pair = {}
        for name, record in (('baseline', previous[qid]), ('candidate', row)):
            out = record['arms']['lexical_first']
            full = out['full_result']
            pair[name] = numeric_results([n for n in labels if n['id'] == qid], full, out['answer'],
                allow_provisional=True, document_registry=bank['documents'])
            capture_rows.append(dict(id=qid, system=name,
                status=full.get('answer_capture', {}).get('status'),
                binding_valid=validate_binding(full, out['answer']),
                errors=full.get('answer_capture', {}).get('errors'),
                abstained=full.get('abstained'), numeric_required=qid in required_ids))
        for old, new in zip(pair['baseline'], pair['candidate']):
            if old['quantity_index'] != new['quantity_index']:
                raise ValueError('Required relation alignment changed')
            rows.append(dict(id=qid, quantity_index=old['quantity_index'], baseline=old, candidate=new))
    if len(rows) != 102:
        raise ValueError('Partial relation comparison')
    systems = {}
    for name in ('baseline', 'candidate'):
        part = [r[name] for r in rows]
        captured = [c for c in capture_rows if c['system'] == name]
        correct = sum(r['correct'] is True for r in part)
        systems[name] = dict(n_correct=correct, n_required=102, strict_lower=correct/102,
            n_unknown=sum(r['correct'] is None for r in part), states=dict(Counter(r['state'] for r in part)),
            failed_checks_nonexclusive=dict(Counter(k for r in part for k,v in r.get('checks', {}).items() if v is False)),
            n_complete_capture=sum(c['status'] == 'captured' for c in captured), n_outputs=len(candidate))
    report = dict(scope='All94 numeric questions /102 relations plus qualitative controls; development repair experiment, NOT full498 acceptance',
        systems=systems, n_numeric_regressions=sum(r['baseline']['correct'] is True and r['candidate']['correct'] is not True for r in rows),
        n_numeric_recoveries=sum(r['baseline']['correct'] is not True and r['candidate']['correct'] is True for r in rows),
        source_sha256={str(p): sha(p) for p in (a.baseline/'paired_answers.json', a.candidate/'paired_answers.json', a.candidate/'manifest.json')},
        all_outcomes_retained=True, gold_scorer_unchanged=True, n_unseen_questions=0,
        factual_citation_audit_performed=False, all498_target_proven=False)
    save(a.output/'comparison.json', report)
    save(a.output/'numeric_relations102.json', rows)
    save(a.output/'capture_outcomes.json', capture_rows)
    print(report)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    compare(p.parse_args())
