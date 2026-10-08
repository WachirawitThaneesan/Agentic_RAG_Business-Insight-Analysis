"""Bind operational direct-quote recoveries to the unchanged full498 audit.

Previously valid decisions are immutable. Only previously failed decisions may
be replaced, after exact payload comparison and the original strict validators.
No model calls, inferred quotes, answer edits, or scoring-contract changes.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from backend.eval.comprehensive import claim_metrics, validate_judgment
from backend.eval.contract_replay import replay_answer, summarize_replay
from scripts.audit_capture_run import cached_input_path, read_raw_judgment
from scripts.evaluate_comprehensive import load, save, sha, judge_payload, summarize


def merge(a):
    records = load(a.run_dir/'paired_answers.json')
    if len(records) != 498 or len({r['id'] for r in records}) != 498:
        raise ValueError('Full498 actual outputs required')
    rows = load(a.base_audit/'details.json')
    replayed = {r['id']: r for r in load(a.base_audit/'contract_details.json')}
    failed = {r['id'] for r in load(a.base_audit/'failures.json')}
    if len(rows) != 498 or set(replayed) & failed or len(replayed)+len(failed) != 498:
        raise ValueError('Base audit outcomes incomplete or ambiguous')
    recovery_rows = load(a.direct_audit/'details.json')
    if {r['id'] for r in recovery_rows} != failed:
        raise ValueError('Recovery may cover only and every prior operational failure')
    for directory in (a.base_audit, a.direct_audit):
        lock = load(directory/'method_lock.json')
        for path, digest in lock['inputs_sha256'].items():
            if sha(path) != digest:
                raise ValueError('Parent frozen audit input changed: '+path)
        for path, digest in lock['code_sha256'].items():
            if sha(path) != digest:
                raise ValueError('Parent audit code changed: '+path)
    a.output.mkdir(parents=True, exist_ok=False)
    bank = load(a.run_dir/'reference_locked.json')
    labels = load(a.run_dir/'numeric_labels_locked.json')
    by_id = {r['id']: r for r in records}
    remaining = []
    lineage = []
    for row in rows:
        key = row['id']
        parent_dir = a.direct_audit if key in failed else a.base_audit
        paths = list((parent_dir/'judge_outputs').glob('*__lexical_first__'+key+'.json'))
        if len(paths) != 1:
            raise ValueError('Ambiguous parent actual decision')
        parent = paths[0]
        result = load(parent)
        source_input = cached_input_path(parent)
        check_row = dict(row)
        if key in failed:
            check_row['fragment_quotes'] = False
        if source_input is None or load(source_input) != judge_payload(check_row):
            raise ValueError('Recovery question/answer/evidence differs: '+key)
        if key in failed:
            if result.get('judgment'):
                raw = read_raw_judgment(result, check_row)
                validated = validate_judgment(deepcopy(raw), context=row['context'], sources=row['sources'],
                    reference=row['reference'], evidence_blocks=row['evidence_blocks'],
                    captured_claims=row.get('captured_answer_claims'), actual_citations=row.get('actual_claim_citations'))
                record = by_id[key]['arms']['lexical_first']
                replay = replay_answer(row, raw, record, [n for n in labels if n['id'] == key],
                    allow_provisional=True, citation_support_decisions=raw.get('actual_citation_audit'))
                replay['arm'] = 'lexical_first'
                replayed[key] = replay
                row['claims'] = claim_metrics(validated)
                row['judge_status'] = 'measured'
                result = {**result, 'judgment': validated, 'reused_direct_quote_protocol': True}
            else:
                remaining.append(dict(id=key, arm='lexical_first', reason=result['last_validation_error']))
        copied = {**result, 'reused_from': str(parent), 'parent_sha256': sha(parent), 'new_sdk_attempts': 0}
        save(a.output/'judge_outputs'/(row['key']+'.json'), copied)
        save(a.output/'judge_inputs'/(row['key']+'.json'), load(source_input))
        lineage.append(dict(id=key, parent=str(parent), parent_sha256=sha(parent),
            prior_valid_unchanged=key not in failed, direct_recovery=key in failed))
    replays = [replayed[r['id']] for r in rows if r['id'] in replayed]
    save(a.output/'details.json', rows)
    save(a.output/'contract_details.json', replays)
    save(a.output/'failures.json', remaining)
    save(a.output/'summary.json', summarize(rows, []))
    save(a.output/'contract_summary.json', {'lexical_first': summarize_replay(replays,
        n_total=498, n_numeric_labels=len(labels), n_total_answerable=498)})
    save(a.output/'method_lock.json', dict(scope='Full498 exact-payload merge of validated parents; original contracts unchanged',
        sdk_attempts=0, inputs_sha256={str(p): sha(p) for p in (a.run_dir/'paired_answers.json',
            a.base_audit/'method_lock.json', a.direct_audit/'method_lock.json')},
        code_sha256={f: sha(f) for f in (__file__, 'backend/eval/comprehensive.py', 'backend/eval/contracts.py',
            'backend/eval/contract_replay.py', 'scripts/audit_capture_run.py')},
        previous_valid_decisions_retained=len(rows)-len(failed), human_confirmed=False))
    save(a.output/'lineage.json', lineage)
    print(dict(n_total=498, n_valid=len(replays), n_failed=len(remaining), new_sdk_attempts=0))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir', 'base-audit', 'direct-audit', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    merge(p.parse_args())
