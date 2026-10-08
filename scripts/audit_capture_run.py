"""Frozen-output factual/context and actual emitted-link audit, with checkpoints."""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

from scripts.evaluate_comprehensive import load, save, sha, prepare, judge, summarize
from scripts.bounded_cloud_meter import BoundedCloudMeter
from backend.eval.comprehensive import claim_metrics
from backend.eval.comprehensive import validate_judgment
from scripts.evaluate_comprehensive import judge_payload
from scripts.evaluate_comprehensive import bind_judge_claim_indices


def read_raw_judgment(result,row):
    parse_row=dict(row)
    if result.get('reused_direct_quote_protocol'):parse_row['fragment_quotes']=False
    return bind_judge_claim_indices(json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',result['raw_outputs'][-1].strip())),parse_row)


def cached_input_path(output_path):
    """Follow verified reuse lineage when an older runner omitted its input copy."""
    current = output_path
    seen = set()
    while current not in seen and current.exists():
        seen.add(current)
        input_path = current.parent.parent/'judge_inputs'/current.name
        if input_path.exists():
            return input_path
        result = load(current)
        if not result.get('reused_from'):
            return None
        parent = Path(result['reused_from'])
        if not parent.exists() or sha(parent) != result.get('parent_sha256'):
            return None
        current = parent
    return None
from backend.eval.contract_replay import replay_answer, summarize_replay


async def run(a):
    a.output.mkdir(parents=True, exist_ok=a.resume)
    records=load(a.run_dir/'paired_answers.json')
    bank=load(a.run_dir/'reference_locked.json'); ids={r['id'] for r in records}
    bank['items']=[q for q in bank['items'] if q['id'] in ids]
    save(a.output/'reference_subset_locked.json',bank)
    arms=sorted({arm for r in records for arm in r['arms']})
    answers={arm:[r['arms'][arm] for r in records if arm in r['arms']] for arm in arms}
    for arm,rows in answers.items(): save(a.output/(arm+'_answers.json'),rows)
    paths=load(a.pdf_paths)
    config={'cohorts':[{'name':a.run_dir.name,'reference':str(a.output/'reference_subset_locked.json'),
        'pdf_paths':paths,'answers':{arm:str(a.output/(arm+'_answers.json')) for arm in arms}}]}
    save(a.output/'config_locked.json',config)
    rows,retrieval,inputs=prepare(config)
    for row in rows:
        row['compact_judge_payload']=getattr(a,'compact_payload',False) or getattr(a,'fragment_quotes',False)
        row['fragment_quotes']=getattr(a,'fragment_quotes',False)
        row['portable_judge_schema']=getattr(a,'portable_schema',False)
        row['judge_thinking_budget']=getattr(a,'judge_thinking_budget',None)
    lock={'inputs_sha256':inputs,'code_sha256':{f:sha(f) for f in
          ['scripts/audit_capture_run.py','scripts/evaluate_comprehensive.py','backend/eval/comprehensive.py',
           'backend/eval/contracts.py','backend/eval/contract_replay.py']},'human_confirmed':False,
          'scope':'AI entailment + quote binding; actual app links audited explicitly; no answer regeneration',
          'reuse_audit':str(a.reuse_audit) if a.reuse_audit else None,
          'retry_unresolved':a.retry_unresolved,
          'compact_payload':getattr(a,'compact_payload',False)}
    lock['max_output_tokens']=getattr(a,'max_output_tokens',6000)
    lock['portable_schema']=getattr(a,'portable_schema',False)
    lock['judge_thinking_budget']=getattr(a,'judge_thinking_budget',None)
    if getattr(a,'fragment_quotes',False):
        lock['fragment_quotes']=True
        lock['code_sha256']['scripts/evidence_quote_fragments.py']=sha('scripts/evidence_quote_fragments.py')
    if (a.output/'method_lock.json').exists() and load(a.output/'method_lock.json')!=lock:
        raise ValueError('Resume audit code/inputs changed')
    save(a.output/'method_lock.json',lock)
    labels=load(a.run_dir/'numeric_labels_locked.json')
    results=[]; failures=[]
    with BoundedCloudMeter(a.budget,a.output,max_new_attempts=None) as meter:
        for i,row in enumerate(rows,1):
            meter.phase.update(stage='actual_answer_judge',id=row['id'],arm=row['arm'])
            path=a.output/'judge_outputs'/f"{row['key']}.json"
            result=load(path) if path.exists() else None
            from_saved_cache=result is not None
            if result is None and a.reuse_audit:
                outputs=list((a.reuse_audit/'judge_outputs').glob('*__'+row['arm']+'__'+row['id']+'.json'))
                candidates=[cached_input_path(p) for p in outputs]
                candidates=[p for p in candidates if p is not None]
                old_row=dict(row);old_row['fragment_quotes']=False
                exact_payload=(len(candidates)==1 and load(candidates[0])==judge_payload(row))
                direct_payload=(len(candidates)==1 and row.get('fragment_quotes') and load(candidates[0])==judge_payload(old_row))
                if exact_payload or direct_payload:
                    parent=outputs[0]
                    previous=load(parent)
                    if previous.get('judgment'):
                        try:
                            raw_protocol_direct=bool(direct_payload or previous.get('reused_direct_quote_protocol'))
                            raw=read_raw_judgment({**previous,'reused_direct_quote_protocol':raw_protocol_direct},row)
                            validated=validate_judgment(deepcopy(raw),context=row['context'],sources=row['sources'],
                                reference=row['reference'],evidence_blocks=row['evidence_blocks'],
                                captured_claims=row.get('captured_answer_claims'),actual_citations=row.get('actual_claim_citations'))
                            record=next(r for r in answers[row['arm']] if r['id']==row['id'])
                            replay=replay_answer(row,raw,record,[n for n in labels if n['id']==row['id']],
                                allow_provisional=True,citation_support_decisions=raw.get('actual_citation_audit'))
                            unresolved=set(replay['missing_dimensions'])-{'numeric_tuple'}
                            if not a.retry_unresolved or not unresolved:
                                result={**previous,'judgment':validated,'reused_from':str(parent),
                                        'parent_sha256':sha(parent),'new_sdk_attempts':0,
                                        'reused_direct_quote_protocol':raw_protocol_direct}
                                save(path,result)
                                save(a.output/'judge_inputs'/path.name,judge_payload(row))
                        except (ValueError,TypeError,KeyError):
                            pass
            if result is None:result=await judge(row,a.output,max_output_tokens=getattr(a,'max_output_tokens',6000))
            row['judge_status']=result['status']
            if result.get('judgment'):
                row['claims']=claim_metrics(result['judgment'])
                # Raw judgments retain supported-but-unverifiable quote states.
                raw=read_raw_judgment(result,row)
                record=next(r for r in answers[row['arm']] if r['id']==row['id'])
                replay=replay_answer(row,raw,record,[n for n in labels if n['id']==row['id']],
                    allow_provisional=True,citation_support_decisions=raw.get('actual_citation_audit'))
                replay['arm']=row['arm'];results.append(replay)
            else:failures.append({'id':row['id'],'arm':row['arm'],'reason':result['last_validation_error']})
            # Cached raw outcomes are already durable. Rebuild their derivable
            # aggregates in memory, rather than rewriting the full corpus on
            # every cached row after an interruption. New outcomes still get
            # an immediate checkpoint; the final row always writes everything.
            if not from_saved_cache or i==len(rows):
                save(a.output/'details.json',rows);save(a.output/'contract_details.json',results)
                save(a.output/'failures.json',failures);save(a.output/'summary.json',summarize(rows,[]))
                save(a.output/'contract_summary.json',{arm:summarize_replay([r for r in results if r['arm']==arm],
                    n_total=len(bank['items']),n_numeric_labels=sum(n['id'] in ids for n in labels),
                    n_total_answerable=sum(q.get('answerable',True) for q in bank['items'])) for arm in arms})
            print(f'Audited {i}/{len(rows)} {row["id"]} {row["arm"]}: {result["status"]}',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir','pdf-paths','budget','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--reuse-audit',type=Path,help='Reuse validated successful decisions only when exact judge payload matches')
    p.add_argument('--retry-unresolved',action='store_true',help='Rejudge reused records with unknown quote/link dimensions')
    p.add_argument('--compact-payload',action='store_true',help='Keep actual context once, only cited sources, and explicit captured claim indices')
    p.add_argument('--fragment-quotes',action='store_true',help='Reviewer selects original text fragment IDs; location is bound in code, entailment remains AI')
    p.add_argument('--max-output-tokens',type=int,default=6000,help='Frozen per-response output budget; operational schema recovery does not alter answer or gold')
    p.add_argument('--portable-schema',action='store_true',help='Omit provider array count constraints; exact counts remain mandatory in local validators')
    p.add_argument('--judge-thinking-budget',type=int,help='Optional bounded reasoning for operational judge recovery; valid matching verdicts still reused, old failures retained')
    a=p.parse_args();asyncio.run(run(a))


if __name__=='__main__':main()
