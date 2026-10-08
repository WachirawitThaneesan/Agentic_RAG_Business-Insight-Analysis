"""Compare old capture to repaired binding on unchanged saved model outputs.

No generation, inferred annotations, label aliases, or judge retries occur.
"""
from collections import Counter
from pathlib import Path
import json

from backend.services import answer_capture as c
from backend.eval.contract_replay import numeric_results
from scripts.evaluate_comprehensive import load, save, sha


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'TestFile/evaluation_completion_2026-10-07'
OUT = ROOT/'TestFile/evaluation_A_2026-10-08/stage2_capture_replay'


def main():
    if OUT.exists():
        raise ValueError('Preserve existing replay; use a new output')
    source = OLD/'final133_v2'
    records = load(source/'paired_answers.json')
    labels = load(source/'numeric_labels_locked.json')
    bank = load(source/'reference_locked.json')
    grouped = {}
    for label in labels: grouped.setdefault(label['id'], []).append(label)
    rows = []
    numeric = []
    for row in records:
        for arm, record in row['arms'].items():
            full = record['full_result']
            if not c.validate_binding(full, record['answer']):
                raise ValueError('Saved original answer capture mismatch')
            cap = full['answer_capture']
            event = None
            for call in reversed(record.get('model_calls', [])):
                if not isinstance(call.get('response'), str): continue
                if c.digest(call.get('prompt') or '') != cap.get('prompt_sha256'): continue
                draft, payload = c.decode(call['response'])
                if payload is None or c.digest(draft) != cap.get('draft_sha256'): continue
                event = {'draft':draft,'payload':payload,'context':full['evidence_context'],
                         'blocks':full['evidence_blocks'],'prompt_sha256':cap['prompt_sha256'],'origin':cap['origin']}
                break
            candidate = c.finalize(full, [event]) if event else full
            for field in ('answer','answer_claims','claim_citations','evidence_context','evidence_blocks'):
                if candidate.get(field) != full.get(field):
                    raise ValueError('Replay changed actual answer, claims, links or context')
            if not c.validate_binding(candidate, record['answer']):
                raise ValueError('Candidate capture hash mismatch')
            old_numeric = numeric_results(grouped.get(row['id'], []), full, record['answer'],
                                          allow_provisional=True, document_registry=bank['documents'])
            new_numeric = numeric_results(grouped.get(row['id'], []), candidate, record['answer'],
                                          allow_provisional=True, document_registry=bank['documents'])
            for before, after in zip(old_numeric, new_numeric):
                numeric.append({'id':row['id'],'arm':arm,'quantity_index':before['quantity_index'],
                                'baseline':before,'candidate':after})
            rows.append({'id':row['id'],'arm':arm,'raw_generation_found':bool(event),
                         'baseline_status':cap['status'],'candidate_status':candidate['answer_capture']['status'],
                         'baseline_errors':cap['errors'],'candidate_errors':candidate['answer_capture']['errors'],
                         'baseline_numeric_facts':full.get('numeric_facts'),
                         'candidate_numeric_facts':candidate.get('numeric_facts'),
                         'answer_sha256':c.digest(record['answer']),
                         'unchanged_answer_claims_links_context':True})
    summaries = {}
    for arm in sorted({r['arm'] for r in rows}):
        part = [r for r in rows if r['arm']==arm]
        nums = [r for r in numeric if r['arm']==arm]
        item = {'n_answers':len(part),'n_raw_generation_available':sum(r['raw_generation_found'] for r in part)}
        for prefix in ('baseline','candidate'):
            item[prefix] = {'capture_states':dict(Counter(r[prefix+'_status'] for r in part)),
                'errors_nonexclusive':dict(Counter(e for r in part for e in r[prefix+'_errors'])),
                'n_numeric_required':len(nums),'n_numeric_measured':sum(r[prefix]['correct'] is not None for r in nums),
                'n_numeric_correct':sum(r[prefix]['correct'] is True for r in nums),
                'numeric_states':dict(Counter(r[prefix]['state'] for r in nums))}
        item['capture_recovered'] = [r['id'] for r in part if r['baseline_status']!='captured' and r['candidate_status']=='captured']
        item['capture_regressions'] = [r['id'] for r in part if r['baseline_status']=='captured' and r['candidate_status']!='captured']
        item['strict_numeric_regressions'] = [{'id':r['id'],'quantity_index':r['quantity_index']} for r in nums
                                             if r['baseline']['correct'] is True and r['candidate']['correct'] is not True]
        summaries[arm] = item
    save(OUT/'details.json', rows)
    save(OUT/'numeric_details.json', numeric)
    save(OUT/'summary.json', {'scope':'Raw-emitted-generation binder replay, identical answers/claims/links/context and locked labels/scorer. Final133 is development. Not fresh generation or full quality acceptance.',
        'new_sdk_attempts':0,'human_confirmed':False,'arms':summaries,
        'inputs_sha256':{'answers':sha(source/'paired_answers.json'),'labels':sha(source/'numeric_labels_locked.json')},
        'binder_sha256':sha(Path(c.__file__))})
    failures = load(OLD/'final133_audit_v2/failures.json')
    breakdown = Counter('non_json_or_empty_response_unresolved' if r['reason'].startswith('Expecting value:')
        else 'invalid_claim_identity_schema' if 'captured claim' in r['reason']
        else 'invalid_or_missing_evidence_fragment' for r in failures)
    save(OUT/'judge_failure_breakdown.json', {'n_failed':len(failures),'counts':dict(breakdown),
        'retry_dispatched':False,'original_failures_preserved':True,
        'reason':'This binder/table study does not invalidate exact-payload judging. Empty/non-JSON outcomes remain unresolved, invalid supporting fragments never become passes.',
        'failures':failures})
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
