"""Reconcile delivery metadata only after offline evidence verification."""
import datetime
import shutil
from pathlib import Path

from scripts.evaluate_comprehensive import load,save,sha
from scripts.bounded_cloud_meter import BoundedCloudMeter

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
DOC=ROOT/'docs/evaluation-completion-2026-10-07'


def main():
    verification=load(DOC/'INTEGRITY_VERIFICATION.json')
    assert verification['all_532_judge_outcomes_accounted_for']
    lineage=load(OUT/'ledger_lineage.json');ledger=load(OUT/'resource_ledger.json')
    canonical=Path(lineage['parent_path'])
    meter=BoundedCloudMeter(canonical,OUT,max_new_attempts=0)
    with meter.ledger_lock():
        digest=sha(canonical)
        previous=lineage.get('canonical_reconciliation',{})
        if digest in (lineage['parent_sha256'],previous.get('exported_sha256')):
            if not (OUT/'canonical_ledger_before_reconciliation.json').exists():
                shutil.copy2(canonical,OUT/'canonical_ledger_before_reconciliation.json')
            save(canonical,ledger)
            lineage['canonical_reconciliation']={'status':'exported_after_all_workers_finished',
                'exported_sha256':sha(canonical),'sdk_attempts_recorded_lower_bound':ledger['sdk_attempts'],
                'usage_reset':False}
        else:
            lineage['canonical_reconciliation']={'status':'concurrent_change_preserved_no_overwrite',
                'observed_canonical_sha256':digest,'current_continuation_ledger':str((OUT/'resource_ledger.json').resolve()),
                'usage_reset':False}
    lineage['policy']='Inherited counters remain fixed for delta accounting; final reconciliation is guarded by the original/previous canonical hash'
    save(OUT/'ledger_lineage.json',lineage)
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    status='''# Evaluation completion status — 7 October 2026

Estimated full-plan workflow completion: **about90–95%**. This is an approximate assessment across the eight stages, not a measured accuracy score or a time estimate. The quality objective is **not complete**.

The planned final evaluation execution is delivered:133 questions ×4 systems =532 saved answers and532 recorded judge outcomes. Failed/unresolved judgments remain in the denominators. Integrity checks reproduced the metrics offline and verified frozen inputs/backend code and exact judge payloads. ZIP/hash verification is recorded separately in ARCHIVE_VERIFICATION.json.

| Stage | Delivered evidence | Remaining limitation |
|---|---|---|
| 0 Preparation | Frozen inputs/code, isolated runs, checkpoints and cumulative accounting | Interrupted usage not recoverable from unreadable writes remains unknown; counters are lower bounds |
| 1 References/scorer | Versioned source review, bound claims, strict numeric/citation grading and tests | AI provisional; remaining literal identity/reference limitations are disclosed |
| 2 Retrieval | Same-label498-question replay and118-question new-report frozen ranking comparison | New-report90% target is unmet; incomplete qrels limit precision/nDCG |
| 3 Context/table | Exact model contexts, provenance and original-PDF relationship audit |53 historical unknown probes and one invalid source-probe page remain disclosed |
| 4 Answers/citations | Matched50-pair development plus final four-system generation/judging | New-report capture/numeric/complete-success quality gates are unmet; missingness is explicit |
| 5 Ingestion | Real32-page OCR/upload, staging/restart/rollback and8-page upload/scraped registration comparison | Selected-page evidence; full-report production OCR/migration is not certified |
| 6 New reports | BCP/WHAUP/CPN native-report transfer test with118 answerable questions and15 controls | Seven-question technical-repair exposure; ownership-family independence not certified |
| 7 Delivery | Thai report, metrics/denominators, command guide, raw evidence/code, resource lineage and archive index | Quality acceptance remains partial; no500–1000 question expansion while gates fail |

See REPORT_th.md, METRICS.json and NEXT_ACTION.md. Future tuning must treat this transfer set as development and reserve new reports for an independent final test. Human confirmation=0; no deployment/push or production DB deletion.
'''
    (DOC/'COMPLETION_STATUS.md').write_text(status,encoding='utf-8')
    audit=ROOT/'docs/EVALUATION_PLAN_COMPLETION_AUDIT_2026-10-07.md'
    original=audit.read_text(encoding='utf-8')
    start=original.index('**Latest checkpoint:**');end=original.index('\n\nLatest report:',start)
    latest='**Latest checkpoint:** roughly **90–95% workflow completion** (estimated, not accuracy). The planned final evaluation execution is delivered: all532 answers and all532 judge outcomes are accounted for, with offline integrity checks. Failed/unresolved judgments and unmet quality targets remain explicit. The full plan has not reached100% quality acceptance. The70% assessment below is historical.'
    audit.write_text(original[:start]+latest+original[end:],encoding='utf-8')
    marker='## Final evaluation delivery — 2026-10-07'
    note='\n\n'+marker+'\n\nAll532 final answers and judge outcomes are saved; offline integrity/metric reproduction passed. See docs/evaluation-completion-2026-10-07/REPORT_th.md, COMPLETION_STATUS.md, METRICS.json and ARCHIVE_VERIFICATION.json. Approximate full-plan workflow completion90–95%; quality objective remains partial. This is native-report transfer with disclosed technical-repair exposure, not pristine never-exposed questions or certified full-report OCR. Interrupted accounting is preserved as lower bounds, not reset. No500–1000 expansion while quality gates fail. Next actions/commands are recorded in that report directory.\n'
    for name in ['docs/RAG_EVALUATION_IMPROVEMENT_PLAN_2026-10-05.md','docs/HANDOFF_2026-10-05.md','docs/goals/2026-10-05-01-rag-evaluation-continuation.md']:
        path=ROOT/name
        if marker not in path.read_text(encoding='utf-8'):
            with path.open('a',encoding='utf-8') as stream:stream.write(note)
    save(DOC/'DELIVERY_METADATA.json',{'recorded_at_utc':timestamp,'workflow_completion_estimate_range_percent':[90,95],
        'planned_evaluation_execution_complete':True,'quality_goal_completed':False,'human_confirmed':False,
        'canonical_reconciliation':lineage['canonical_reconciliation']})


if __name__=='__main__':main()
