"""Require measured development coverage, then freeze the final transfer test."""
from pathlib import Path
import datetime
import importlib.metadata

from scripts.evaluate_comprehensive import load, save, sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
OLD=Path(r'C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs\plan_completion_authorized_v1')


def main():
    capture=load(OUT/'development50_v2_rescore/summary.json')
    audit=load(OUT/'audit50_fragment_v1/contract_summary.json')
    details=load(OUT/'audit50_fragment_v1/contract_details.json')
    gates={}
    for arm,s in capture['arms'].items():
        rows=[r for r in details if r['arm']==arm]
        missing=50-len(rows)
        eligible=sum(len(r['complete_gate']) for r in rows)+missing*12
        known=sum(v is not None for r in rows for v in r['complete_gate'].values())
        gates[arm]={'capture_coverage':s['capture_coverage'],'numeric_coverage':s['numeric']['coverage'],
            'judge_record_coverage':len(rows)/50,'metric_gate_unit_coverage':known/eligible,
            'actual_mapping_question_coverage':audit[arm]['citation']['n_questions_actual_mapping_measured']/50,
            'n_generation_errors':s['n_errors'],'n_claims_without_citation':s['n_claims_without_citation'],
            'missing_dimensions':audit[arm]['complete_answer_success']['missing_dimensions']}
    approved=all(g['capture_coverage']>=.95 and (g['numeric_coverage'] is None or g['numeric_coverage']>=.95)
        and g['judge_record_coverage']>=.95 and g['metric_gate_unit_coverage']>=.95
        and g['actual_mapping_question_coverage']>=.95 and not g['n_generation_errors']
        and not g['n_claims_without_citation'] for g in gates.values())
    gate={'approved_from_measured_development_evidence':approved,'gates':gates,
        'thresholds':{'capture':.95,'numeric':.95,'judge':.95,'metric_units':.95,'actual_mapping':.95},
        'unresolved_results_preserved':True,'quality_targets_met':False,
        'scope':'Preplanned 133-question new-issuer native transfer evaluation; no expansion to 500–1000 answers while quality targets remain',
        'selected_improved_policy':'lexical_first','selection_reason':'Retain validated production policy; paired50 factual support and complete-success lower bound favor lexical. Numeric literal scores alone do not justify a policy change.',
        'capture_sha256':sha(OUT/'development50_v2_rescore/summary.json'),
        'audit_sha256':sha(OUT/'audit50_fragment_v1/contract_summary.json'),
        'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(OUT/'FINAL_DISPATCH_GATE.json',gate)
    if not approved:raise ValueError('Measured development coverage gate still fails: '+str(gates))
    files=[p for base in ['backend/eval','backend/services','scripts'] for p in (ROOT/base).rglob('*.py')
           if '__pycache__' not in p.parts]
    packages={}
    for package in ['google-genai','numpy','sqlalchemy','pymupdf','httpx','asyncpg','pydantic']:
        try:packages[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:packages[package]=None
    save(OUT/'FINAL_CODE_AND_INPUT_FREEZE.json',{'recorded_before_final_inference':True,
        'code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in files},
        'inputs_sha256':{str(p):sha(p) for p in [OLD/'heldout_fact_dedup_v4/reference_locked.json',
            OLD/'heldout_fact_dedup_v4/numeric_labels_locked.json',OLD/'heldout_fact_dedup_v4/query_vectors.npz',
            OLD/'heldout_fact_dedup_v4/selection_locked.json',OLD/'heldout_native_corpus_prepared/corpus.json',
            OLD/'heldout_native_corpus_prepared/embeddings.npz']},'packages':packages,
        'policies':['bm25_thai','dense','simple_rag','lexical_first'],'human_confirmed':False,
        'no_tuning_after_final_predictions':True,'scope':'All four arms share frozen full native report text, models and capture. Keyword/dense full-agent baselines and one-retrieval simple RAG are system comparisons.'})
    print('Final dispatch coverage gates passed; quality targets remain')


if __name__=='__main__':main()
