"""Offline integrity/count verification of the completed evaluation evidence."""
from collections import Counter
from pathlib import Path

from scripts.evaluate_comprehensive import load, save, sha
from scripts.package_evaluation_completion import summarize

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
DOC=ROOT/'docs/evaluation-completion-2026-10-07'


def main():
    run=OUT/'final133_v2';audit=OUT/'final133_audit_v2'
    records=load(run/'paired_answers.json');bank=load(run/'reference_locked.json')
    ids=[r['id'] for r in records];questions=[q['id'] for q in bank['items']]
    assert len(ids)==133 and len(set(ids))==133 and set(ids)==set(questions)
    arms={'bm25_thai','dense','simple_rag','lexical_first'}
    assert all(set(r['arms'])==arms for r in records)
    manifest=load(run/'manifest.json')
    for name,digest in manifest['code_sha256'].items():
        if name.startswith('backend/'):
            assert sha(ROOT/name)==digest,('Frozen app/scorer changed',name)
    for name,digest in manifest['inputs_sha256'].items():
        assert sha(Path(name))==digest,('Frozen input changed',name)
    for name in ('reference_locked.json','numeric_labels_locked.json'):
        assert sha(run/name)==sha(OUT/'final_input_snapshot'/name)
    expected=load(OUT/'final_judge_shards/expected_payload_sha256.json')
    from scripts.parallel_final_judge_checks import payload_sha
    keys={f'final133_v2__{arm}__{qid}' for qid in ids for arm in arms}
    assert set(expected)==keys
    statuses=Counter()
    for key in sorted(keys):
        path=audit/'judge_outputs'/(key+'.json')
        result=load(path);statuses[result['status']]+=1
        assert result['status'] in ('measured','judge_failed')
        assert payload_sha(load(audit/'judge_inputs'/(key+'.json')))==expected[key],key
    failures=load(audit/'failures.json');details=load(audit/'contract_details.json')
    assert len(details)+len(failures)==532
    assert len(details)==statuses['measured'] and len(failures)==statuses['judge_failed']
    assert len({(r['arm'],r['id']) for r in details})==len(details)
    published=load(DOC/'METRICS.json')['new_issuer_final133']
    assert summarize(run,audit)==published,'Published metrics differ from saved evidence'
    result={'all_532_outputs_saved':True,'all_532_judge_outcomes_accounted_for':True,
        'judge_statuses':dict(statuses),'all_judge_payloads_match_frozen_expected_hashes':True,
        'frozen_backend_and_inputs_unchanged':True,'metrics_reproduced_offline':True,
        'new_cloud_calls':0,'quality_goal_completed':False,
        'generation_sha256':sha(run/'paired_answers.json')}
    save(DOC/'INTEGRITY_VERIFICATION.json',result)
    print(result)


if __name__=='__main__':main()
