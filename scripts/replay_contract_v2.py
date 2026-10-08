"""Replay saved answer judgments under contract v2 without network or model calls."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from copy import deepcopy

from backend.eval.contract_replay import replay_answer, summarize_replay, validate_reference_binding
from backend.eval.contracts import validate_numeric_label
from scripts.evaluate_comprehensive import exact_context, load, save, sha, write_csv


def raw_decision(saved):
    for text in reversed(saved.get('raw_outputs', [])):
        try:
            data = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip()))
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and 'answer_claims' in data:
            return data
    raise ValueError('Missing raw decision; validated verdicts cannot restore raw quote uncertainty')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--answers', type=Path, required=True)
    p.add_argument('--trace', type=Path, required=True)
    p.add_argument('--labels', type=Path, required=True)
    p.add_argument('--policy', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--numeric-annotations', type=Path,
                   help='Separate provisional independent review; never overwrites captured application output')
    a = p.parse_args()
    policy = load(a.policy)
    if sha(a.labels) != policy['numeric_labels_sha256'] or sha(a.reference) != policy['reference_sha256']:
        raise ValueError('Frozen label hashes do not match evaluation policy')
    labels = load(a.labels)
    reference_items = {item['id']: item for item in load(a.reference)['items']}
    byid = defaultdict(list)
    for label in labels:
        validate_numeric_label(label)
        byid[label['id']].append(label)
    records = {r['id']: r for r in load(a.answers)}
    annotations = {}
    if a.numeric_annotations:
        packet = load(a.numeric_annotations)
        if packet['answers_sha256'] != sha(a.answers) or packet.get('human_confirmed') is not False:
            raise ValueError('Review sidecar must bind exact answers and disclose non-human review')
        annotations = {r['id']: r for r in packet['items']}
    trace = load(a.trace)
    inputs = [a.audit/'details.json', a.answers, a.trace, a.labels, a.policy, a.reference]
    if a.numeric_annotations:
        inputs.append(a.numeric_annotations)
    rows, failures = [], []
    details = load(a.audit/'details.json')
    for row in details:
        try:
            validate_reference_binding(row, reference_items[row['id']])
            record = deepcopy(records[row['id']])
            if row['id'] in annotations:
                full = record.setdefault('full_result', {})
                if 'numeric_facts' in full:
                    raise ValueError('Cannot replace existing application numeric facts with independent review')
                facts = annotations[row['id']]['numeric_facts']
                if any(f.get('annotation_origin') != 'independent_review' for f in facts):
                    raise ValueError('Sidecar cannot masquerade as application output')
                full['numeric_facts'] = facts
            if record['answer'] != row['answer']:
                raise ValueError('Captured answer differs from judged answer')
            context, provenance = exact_context(trace, row['id'], row['arm'])
            if context != row['context'] or provenance != 'captured_generation_prompt':
                raise ValueError('Judged context differs from exact captured generation context')
            path = a.audit/'judge_outputs'/f"{row['key']}.json"
            inputs.append(path)
            saved = load(path)
            if saved['status'] != 'measured':
                raise ValueError('Judge did not succeed')
            rows.append(replay_answer(row, raw_decision(saved), record, byid[row['id']],
                allow_provisional=policy.get('allow_provisional_numeric', False)))
        except (KeyError, ValueError, TypeError) as exc:
            failures.append({'id': row['id'], 'state': 'replay_failed', 'reason': str(exc)})
    a.output.mkdir(parents=True, exist_ok=False)
    save(a.output/'details.json', rows)
    save(a.output/'failures.json', failures)
    summary = summarize_replay(rows, n_total=len(details), n_numeric_labels=len(labels))
    summary['numeric_annotation_source'] = 'provisional_independent_ai_review_sidecar' if a.numeric_annotations else 'captured_application_only'
    save(a.output/'summary.json', summary)
    claims = [{'id': r['id'], 'claim_index': i, 'claim': c['text'], 'dimension': dim, **c[dim]}
              for r in rows for i, c in enumerate(r['claims']) for dim in ('faithfulness', 'factual')]
    write_csv(a.output/'claim_states.csv', claims)
    write_csv(a.output/'numeric_tuples.csv', [{'id': r['id'], **n} for r in rows for n in r['numeric']])
    code = ['backend/eval/contract_replay.py', 'backend/eval/contracts.py',
            'backend/eval/comprehensive.py', 'backend/eval/numeric.py',
            'scripts/replay_contract_v2.py', 'scripts/evaluate_comprehensive.py']
    root = Path(__file__).resolve().parents[1]
    for name in code:
        target = a.output/'frozen_code'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root/name).read_bytes())
    save(a.output/'method_lock.json', {
        'summary_version': summary['method_version'], 'input_sha256': {str(x): sha(x) for x in inputs},
        'code_sha256': {n: sha(root/n) for n in code}, 'sdk_attempts': 0,
        'reported_input_tokens_new': 0, 'reported_output_tokens_new': 0,
        'source_scope': 'Saved development smoke20; no new answers, PDF review or human validation',
        'raw_judgments_preserved': True, 'historical_scores_unchanged': True})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
