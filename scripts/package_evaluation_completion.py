"""Aggregate frozen results and package evidence; never generate/tune answers."""
import argparse
from collections import Counter
import csv
import datetime
import json
import hashlib
from pathlib import Path
import zipfile
import shutil
import statistics
import os
import time
from backend.eval.contract_replay import summarize_replay

from backend.eval.comprehensive import wilson
from scripts.evaluate_comprehensive import load,save,sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
DOC=ROOT/'docs/evaluation-completion-2026-10-07'


def summarize(run,audit):
    capture=load(run/'summary.json');contracts=load(audit/'contract_summary.json')
    comprehensive=load(audit/'summary.json')['answers']
    failures=load(audit/'failures.json')
    records=load(run/'paired_answers.json');details=load(audit/'contract_details.json')
    metrics={};bank=load(run/'reference_locked.json');questions={q['id']:q for q in bank['items']}
    for arm,cap in capture['arms'].items():
        rows=[r for r in details if r['arm']==arm]
        planned=[r['arms'][arm] for r in records if arm in r['arms']]
        links=[link for r in rows for link in r['actual_citation'].get('links',[])]
        expected_links=sum(len(r['full_result'].get('claim_citations') or []) for r in planned)
        supported=sum(l['state']=='supported_quote_verified' for l in links)
        known=sum(l['state'] not in ('entailment_not_audited','quote_unverifiable') for l in links)
        summary=contracts[arm]
        success=summary.get('answerable_complete_success',summary['complete_answer_success'])
        controls=summary.get('unanswerable_abstention_success')
        answerable_rows=[r for r in rows if r['answerable']]
        n_answerable=sum(questions[r['id']].get('answerable',True) for r in records)
        claim_counts=summarize_replay(answerable_rows,n_total=n_answerable,
            n_numeric_labels=cap['numeric']['n_required'],n_total_answerable=n_answerable)['claim_states']
        latencies=sorted(float(r['seconds']) for r in planned if isinstance(r.get('seconds'),(int,float)))
        diagnostic=comprehensive[run.name.replace('_rescore','')+'/'+arm] if run.name.replace('_rescore','')+'/'+arm in comprehensive else next(v for k,v in comprehensive.items() if k.endswith('/'+arm))
        actual_answerable=[r['actual_citation'] for r in rows if r['answerable']]
        measured_actual=[c for c in actual_answerable if c.get('citation_claim_recall') is not None]
        metrics[arm]={'planned_questions':capture['n_planned_pairs'],'generated_outputs':cap['n_outputs'],
            'capture_coverage':cap['capture_coverage'],'answer_coverage':cap['answer_coverage'],
            'generation_errors':cap['n_errors'],'refusals':cap['n_refusals'],
            'required_numeric_tuples':cap['numeric'],'judge_coverage':len(rows)/capture['n_planned_pairs'],
            'factual_verified_support_macro':claim_counts['factual']['quote_verified_support_fraction_macro'],
            'faithfulness_verified_support_macro':claim_counts['faithfulness']['quote_verified_support_fraction_macro'],
            'factual_states':claim_counts['factual']['counts'],'faithfulness_states':claim_counts['faithfulness']['counts'],
            'claim_aggregation_scope':'Answerable questions only; all/control claims retained separately',
            'answerable_claim_aggregation':claim_counts,'all_questions_claim_aggregation':summary['claim_states'],
            'failed_judge_reason_counts':dict(Counter(r['reason'] for r in failures if r['arm']==arm)),
            'generation_seconds_observed':{'n':len(latencies),'median':statistics.median(latencies) if latencies else None,
                'p95_empirical':latencies[int(.95*(len(latencies)-1))] if latencies else None,
                'sum_overlapping_question_wall_times':sum(latencies),
                'scope':'Per-output recorded time incl retries; concurrent/instrumented, not a controlled speed comparison'},
            'actual_citation_links':expected_links,'actual_links_audited':len(links),
            'actual_link_evaluation_coverage':known/expected_links if expected_links else None,
            'actual_link_precision_all':supported/expected_links if expected_links and known==expected_links else None,
            'actual_link_precision_lower_bound':supported/expected_links if expected_links else None,
            'actual_citation_claim_recall_macro_measured':sum(c['citation_claim_recall'] for c in measured_actual)/len(measured_actual) if measured_actual else None,
            'n_answerable_actual_claim_recall_measured':len(measured_actual),
            'n_answerable_actual_claim_recall_eligible':sum(questions[r['id']].get('answerable',True) for r in records),
            'reference_and_context_metrics_ai_provisional':{k:v for k,v in diagnostic['judge_metrics'].items() if k in ('factual_recall','context_recall','context_precision_ap','context_usefulness_precision','answer_relevancy_rubric')},
            'micro_claim_metrics_ai_provisional_excluding_proposed_citation_recall':{k:v for k,v in diagnostic['micro_claim_metrics'].items() if k!='citation_claim_recall'},
            'answerable_control_breakdown':cap.get('answerable_control_breakdown'),
            'complete_answer_success':success,'unanswerable_controls':controls,
            'human_confirmed':False,'official_thesis_score_eligible':False}
        for name,key in [('by_report','document'),('by_category','source_kind')]:
            groups={}
            for group in sorted({str(questions[r['id']].get(key,'unspecified')) for r in records}):
                qids={r['id'] for r in records if str(questions[r['id']].get(key,'unspecified'))==group}
                part=[r for r in rows if r['id'] in qids and r['answerable']]
                total=sum(questions[qid].get('answerable',True) for qid in qids)
                passed=sum(r['complete_answer_success'] is True for r in part)
                unresolved=sum(r['complete_answer_success'] is None for r in part)+total-len(part)
                groups[group]={'n_answerable_planned':total,'n_answerable_judged':len(part),
                    'n_complete_pass':passed,'n_unresolved':unresolved,
                    'complete_lower_bound':passed/total if total else None,
                    'complete_measured_rate':passed/total if total and not unresolved else None,
                    'complete_rate_wilson95':wilson(passed,total) if total and not unresolved else None,
                    'interval_limit':'Question-level independence approximation only; shared fact/page variants and three issuers do not support population generalization'}
            metrics[arm][name]=groups
    return metrics


def pct(value):return 'N/A' if value is None else f'{100*value:.2f}%'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--final',action='store_true');a=p.parse_args()
    if a.final and (OUT/'final_judge_shards').exists() and not (OUT/'final_judge_shards/worker_exits.json').exists():
        raise RuntimeError('Parallel judge workers still active; wait for their complete evidence/ledger before packaging')
    DOC.mkdir(parents=True,exist_ok=True)
    delivery=OUT/'delivery_code'
    source_names=['scripts/'+name+'.py' for name in ('parallel_final_judge_checks','verify_final_completion',
        'package_evaluation_completion','supervise_final_evaluation','evaluate_comprehensive','audit_capture_run',
        'evidence_quote_fragments','bounded_cloud_meter','run_capture_paired','continue_evaluation_plan',
        'score_final_frozen_retrieval','observe_completion_resources','diagnose_final_numeric','resume_final_evaluation','finalize_evaluation_metadata')]
    for name in source_names:
        target=delivery/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    save(delivery/'MANIFEST.json',{'scope':'Delivery orchestration and judge helpers; original generation code/input freeze retained separately',
        'files':[{'path':name,'sha256':sha(delivery/name)} for name in source_names]})
    development=summarize(OUT/'development50_v2_rescore',OUT/'audit50_fragment_v1')
    final=summarize(OUT/'final133_v2',OUT/'final133_audit_v2') if a.final else None
    ledger=load(OUT/'resource_ledger.json');parent=load(OUT/'ledger_lineage.json')
    initial=parent.get('inherited_counters') or load(Path(parent['parent_path']))
    delta={k:ledger[k]-initial[k] for k in ('sdk_attempts','known_input_tokens','known_output_tokens','failed_calls_without_complete_usage','paid_ocr_pages_new')}
    result={'as_of_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'development50':development,
        'new_issuer_final133':final,'ledger_totals':ledger,'continuation_usage_since_parent_snapshot':delta,
        'quality_goal_completed':False,'human_confirmed':False,
        'scope':'Development capture repairs and report-level native transfer test; not full-report production OCR or independently human-certified thesis scores'}
    if (OUT/'final_retrieval/summary.json').exists():result['new_issuer_initial_retrieval']=load(OUT/'final_retrieval/summary.json')
    if (OUT/'final_numeric_components/summary.json').exists():result['final_numeric_component_diagnostics']=load(OUT/'final_numeric_components/summary.json')
    save(DOC/'METRICS.json',result)
    flat=[]
    for scope,data in [('development50',development),('new_issuer_final133',final or {})]:
        for arm,metrics in data.items():
            def flatten(data,prefix=''):
                for key,value in data.items():
                    name=prefix+key
                    if isinstance(value,dict):flatten(value,name+'.')
                    elif value is None or type(value) in (int,float,bool):flat.append({'scope':scope,'arm':arm,'metric':name,'value':value})
            flatten(metrics)
    with (DOC/'METRICS.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['scope','arm','metric','value']);writer.writeheader();writer.writerows(flat)
    lines=['# ผลการรับช่วงแผนประเมิน Thai Business RAG — 7 ตุลาคม 2026','',
        '**สถานะ:** '+('รันชุด final transfer และส่งหลักฐานครบตามขอบเขตที่วัด; quality targets ยังไม่ครบ' if a.final else 'งานยังดำเนินอยู่; ชุด development ส่งผลแล้ว และ final transfer กำลังรัน'),'',
        'การทำ evaluation จบไม่ได้แปลว่าระบบตอบถูก 100% คะแนนทั้งหมดเป็น AI provisional, human_confirmed=false และไม่ใช่คะแนน thesis ที่มีผู้ตรวจอิสระรับรอง','',
        '## งานที่ทำจริง','',
        '- แก้ app capture: หน่วยประกอบ/อันดับเปอร์เซ็นต์, comparator ในคำว่า งบประมาณ, equipment IDs, categorical ratings และ feedback ที่ระบุ JSON ที่ผิดจริง',
        '- แก้ scorer ให้ใช้เฉพาะ actual claim→source links ที่แอปส่ง เก็บ returned sources แยก; ไม่ใช้ judge-proposed links เป็น citation ของแอป',
        '- แก้ numeric grading จากฟิลด์ที่ bind กับคำตอบจริง โดยคง sign/value/unit/scale/year/page/comparator และแยก literal-name grading จาก AI semantic identity supplement',
        '- รุ่น v9–v11 ตรวจภาพ PDF แก้ comparator/unit และ alternate evidence/aliases โดยรักษา raw labels/scores เก่า การแก้เกิดหลังเห็นผล development จึงไม่อ้างว่าเป็น blind independent review',
        '- 50 matched questions × 2 rankings รันจริง; ชุด v1 ที่มี capture errors และ failed audit/probes ยังเก็บไว้ ชุด v2 ใช้ app protocol เดียวกันทั้ง 50 คู่',
        '- ตรวจ live upload กับ scraped-file preparation บน 8 หน้าใน DB ทดลองใหม่ ผล hash/page checkpoints ตรงกันและใช้ cloud calls=0 การตรวจนี้ไม่ใช่ fresh OCR accuracy',
        '- ใช้หลักฐาน real Typhoon/Gemini ingestion 32 หน้าจากรอบเดิมร่วมกับ staging/restart/idempotency/rollback; ไม่รวมเป็น fresh unseen OCR',
        '- Freeze code/scorer/inputs ก่อน final inference; 3 รายงานไทยใหม่มี 133 คำถาม (118 answerable, 15 controls), 114 numeric tuples และ 1,980 cached corpus embeddings','',
        '## ผล development 50 คู่','',
        '| Ranking | Capture | Numeric coverage | Literal numeric accuracy (measured subset) | Factual verified support macro | Faithfulness verified support macro | Actual link precision | Complete lower bound |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm,s in development.items():
        n=s['required_numeric_tuples'];cs=s['complete_answer_success']
        lines.append(f"| {arm} | {pct(s['capture_coverage'])} | {pct(n['coverage'])} | {pct(n['accuracy_measured_subset'])} ({n['n_correct']}/{n['n_measurable']}) | {pct(s['factual_verified_support_macro'])} | {pct(s['faithfulness_verified_support_macro'])} | {pct(s['actual_link_precision_all'])} | {pct(cs['strict_lower_bound_all'])} |")
    lines+=['','Complete lower bound เป็นขอบเขตล่างเมื่อยังมี unresolved; ไม่ใช้แทน measured complete-answer accuracy และ quote-unverifiable ไม่ได้พิสูจน์ว่า claim นั้นผิดจริง','',
        '## Final transfer บนรายงานใหม่','']
    if final:
        lines+=['| System | Generated | Capture | Required numeric coverage | Literal numeric accuracy (measured subset) | Factual verified support macro | Faithfulness verified support macro | Actual link precision | Answerable complete lower bound |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for arm,s in final.items():
            n=s['required_numeric_tuples']
            lines.append(f"| {arm} | {s['generated_outputs']}/{s['planned_questions']} | {pct(s['capture_coverage'])} | {pct(n['coverage'])} | {pct(n['accuracy_measured_subset'])} ({n['n_correct']}/{n['n_measurable']}) | {pct(s['factual_verified_support_macro'])} | {pct(s['faithfulness_verified_support_macro'])} | {pct(s['actual_link_precision_all'])} | {pct(s['complete_answer_success']['strict_lower_bound_all'])} |")
        lines+=['','Controls แยกจาก answerable complete-success; ดู numerator/denominator/unknown ของแต่ละระบบใน METRICS.json']
        lines+=['','## Numeric failure decomposition','',
            'ใช้ labels/scorer ที่ล็อกไว้เหมือนเดิม เป็น post-test diagnosis ไม่มี cloud calls; จำนวน failed checks ซ้อนกันได้ ไม่ใช้ component score แทน strict numeric accuracy','',
            '| System | Bound numeric tuples with checks | Value+unit checks passed | Literal identity only failures | Physical page failures |','|---|---:|---:|---:|---:|']
        for arm,s in result.get('final_numeric_component_diagnostics',{}).get('arms',{}).items():
            lines.append(f"| {arm} | {s['n_bound_checks_available']}/{s['n_required']} | {s['n_signed_value_unit_checks_correct']}/{s['n_bound_checks_available']} | {s['n_failure_only_in_literal_company_or_measure']} | {s['failed_check_counts_nonexclusive'].get('page',0)} |")
        lines+=['','Literal identity only failures ไม่ได้พิสูจน์ว่าเป็น synonym ที่ถูกต้อง; ต้องตรวจแยกต่อไป ไม่มีการเปลี่ยน aliases/scorer จาก final outcomes']
    else:lines+=['ยังไม่รายงาน final accuracy ระหว่างที่ inference/judging ไม่ครบ']
    retrieval=result.get('new_issuer_initial_retrieval')
    if retrieval:
        lines+=['','## Initial retrieval บนรายงานใหม่','',
            '| Ranking | Hit@1 | Hit@3 | Hit@5 | Hit@10 |','|---|---:|---:|---:|---:|']
        for arm in ('bm25_thai','dense','simple_rag','lexical_first'):
            values=[retrieval.get(f'{arm}@{k}') for k in (1,3,5,10)]
            lines.append('| '+arm+' | '+' | '.join(f"{pct(v['hit_rate'])} ({v['hits']}/{v['n']})" if v else 'N/A' for v in values)+' |')
        lines+=['','118 answerable questions; 15 controls excluded. ใช้ frozen native corpus/query vectors ไม่มี cloud calls; incomplete page qrels จำกัดการตีความ precision/nDCG และนี่คือ initial query ไม่ใช่ทุก agent follow-up retrieval']
    lines+=['','## ขอบเขตและข้อจำกัด','',
        '- Corpus final เป็น full native report text ไม่ใช่ full-report Typhoon/Gemini OCR; ทุก arm ใช้ corpus/embeddings/questions/models ชุดเดียวกัน ระบบ keyword/dense full agent, simple dense RAG หนึ่ง retrieval และ improved scoped system เป็น system comparison ไม่ใช่ fusion-only ablation',
        '- ไม่มี performance-driven tuning หลังเห็น transfer predictions มี technical adapter repair หลัง partial run แรก: nullable cosine similarity และ follow-up query cache จากนั้น restart ทุก arm/ทุกคำถาม เก็บ first attempt และรายการ 7 คำถามที่มี repeat exposure จึงไม่อ้างว่าเป็น pristine never-exposed question test',
        '- ระหว่าง final v2 มี Windows/OneDrive file-lock ทำให้ checkpoint save หยุด ตรวจ hash และความเท่ากันของ 184 outputs เดิม แล้วกู้ pending output ที่ 185 จากไฟล์เดิม จากนั้น resume เฉพาะ outputs ที่ขาด ไม่ regenerate 185 คำตอบที่จ่ายไปแล้ว; เปลี่ยนเฉพาะ I/O/resume orchestration ดู FINAL_IO_REPAIR_DISCLOSURE.json',
        '- Judge scheduling ใช้ separate processes สำหรับ future arms แล้ว import เฉพาะ cache ที่ payload ตรงกับ original ทุก field; เก็บทั้ง measured/failed outcomes, original cache ที่มีอยู่ชนะเสมอ ไม่เลือกคะแนนที่สูงกว่า หากมี overlap เก็บทั้ง raw outcomes/calls ดู final_judge_shards/scheduling_disclosure.json',
        '- หลัง worker interruption พบ latest ledger/dense journal บางไฟล์เป็น zero bytes: เก็บไฟล์เสียและ journals ก่อน resume, กู้ latest valid global checkpoint ที่ SDK=2909 โดยไม่ reset usage, เพิ่มเฉพาะ flush/fsync ก่อน atomic checkpoint replace (11 tests passed) แล้วลดเหลือสอง workers ไม่มี model/prompt/schema/scorer/label change ดู interruption_recovery_v1; usage ที่อาจหายก่อน checkpoint ไม่ทราบ ดังนั้น SDK/token totals เป็น lower bounds และ cost ยัง N/A',
        '- Resume ไม่เขียน aggregate JSON ที่สร้างใหม่ได้ซ้ำทุก cached row; raw outcomes/SDK ledgers ใหม่ยัง checkpoint ทันที และจุดสุดท้ายเขียน aggregates ครบ การแก้เป็น I/O scheduling เท่านั้น เก็บ old code/method locks และตรวจ metric reproduction หลังจบ ดู CACHE_CHECKPOINT_IO_DISCLOSURE.json',
        '- Report/issuer names และไฟล์ต่างจาก development; ultimate ownership-family independence ไม่ได้รับรอง',
        '- คำถามมี variants ที่ใช้ข้อเท็จจริง/หน้าเดียวกัน; Wilson intervals ใน raw metrics เป็น question-level independence approximation เท่านั้น ไม่ใช่ issuer-population CI หรือหลักฐานความทั่วไปจากเพียงสามรายงาน และไม่รายงาน measured complete rate เมื่อยังมี unresolved',
        '- Numeric labels เป็น inventory ที่ล็อกไว้ ไม่ครอบคลุมตัวเลขทุกตัวในทุกคำตอบ semantic identity supplement ตรวจเพียงความหมาย entity/measure โดยไม่เติม annotation ให้แอปหรือแก้ value/unit/year/page/comparator และแสดง literal scores เดิมแยก',
        '- Ingestion relationship audit เดิมยังมี 53 unknown verdicts/หนึ่ง invalid source-probe page และ TOC ที่ถอดเป็น table (ไม่มี CSV numeric cells) ไม่อ้างว่าตรวจทุก cell ผ่าน',
        '- ไม่ขยาย 500–1,000 cloud answers ระหว่างที่ quality targets ยังไม่ผ่าน งานนี้ไม่มี commit/push/deploy หรือการลบ production DB','',
        '## ทรัพยากร','',f"SDK attempts ที่บันทึกได้สะสม {ledger['sdk_attempts']} (lower bound หากมี accounting_recovery); known input {ledger['known_input_tokens']:,}; known output {ledger['known_output_tokens']:,}; failed attempts ที่ usage ไม่ครบ {ledger['failed_calls_without_complete_usage']}; paid OCR unique pages สะสม {ledger['paid_ocr_pages_new']}",
        f"เพิ่มจาก parent snapshot: {json.dumps(delta,ensure_ascii=False)}",
        'Cloud USD cost/cloud memory = N/A ไม่ถือ failed calls ว่าใช้ฟรี RSS/GPU ที่สังเกตเป็น partial concurrent observations ไม่ใช่ isolated peak หรือ controlled speed benchmark','',
        '## หลักฐาน','',
        '- Raw results: `TestFile/evaluation_completion_2026-10-07/`',
        '- `FINAL_DISPATCH_GATE.json`, `FINAL_CODE_AND_INPUT_FREEZE.json`, per-run frozen code/labels, raw SDK traces/judge inputs/outputs, versioned label changes, resource ledger และ tests JUnit',
        '- METRICS.json เก็บ denominators/missingness และแยก scope ของผล; metrics CSV เป็นข้อมูลสรุป ไม่ใช่ Ragas official scores']
    (DOC/'REPORT_th.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (DOC/'NEXT_ACTION.md').write_text('# งานถัดไป\n\n'+('Final transfer รันแล้ว ห้ามใช้ชุดเดิม tune แล้วยังเรียกว่า unseen หากต้องปรับระบบให้ย้ายชุดนี้เป็น development และหา holdout ใหม่\n\n' if a.final else 'Final transfer กำลังรัน อย่าเริ่มงานซ้ำหรือเปลี่ยน code/scorer ใน inference ที่ล็อกแล้ว\n\n')+
        'Quality goal ยังไม่ completed ให้ใช้ per-question failure/missing dimensions แยกคอขวด extraction/context/claims/citations/numeric แล้ววัดด้วย labels/scorer รุ่นเดียวกัน รักษา old raw evidence ทุกชุด\n\n'+
        'Priorities from final numeric component diagnostics: company/measure relation binding, physical page provenance, signed value plus compound unit, and omitted required relations. Literal identity failures need independent source review before calling them synonyms. Do not weaken strict criteria to raise a headline score. Validate protocol changes on development, pass coverage/quality gates, then freeze and test new reports. No500-1000 cloud expansion while gates fail.\n\n'+
        'Raw: TestFile/evaluation_completion_2026-10-07/final_numeric_components/{summary,details}.json. Reproduction and resume commands: COMMANDS.md.\n',encoding='utf-8')
    if a.final:
        from scripts.verify_final_completion import main as verify_integrity
        verify_integrity()
        from scripts.finalize_evaluation_metadata import main as finalize_metadata
        finalize_metadata()
        save(DOC/'PACKAGE_STATE_SNAPSHOT.json',{'planned_outputs':532,'all_outcomes_accounted_for':True,
            'quality_goal_completed':False,'scope':'Immutable delivery snapshot; live controller logs/state are excluded'})
        index=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
            for base in [OUT,DOC] for p in base.rglob('*') if p.is_file() and p.suffix not in ('.duckdb','.wal','.zip','.lock')
            and p.name not in ('samples.jsonl','ARTIFACT_INDEX.json','ARCHIVE_VERIFICATION.json','RUN_STATE.json','launcher.log','launcher_error.log')
            and not p.name.endswith('.zip.pending')
            and not p.name.startswith('.env')]
        save(DOC/'ARTIFACT_INDEX.json',index)
        archive=OUT/'evaluation_completion_evidence.zip'
        pending=archive.with_name(archive.name+'.pending')
        with zipfile.ZipFile(pending,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
            for entry in index:bundle.write(ROOT/entry['path'],entry['path'])
            bundle.write(DOC/'ARTIFACT_INDEX.json',(DOC/'ARTIFACT_INDEX.json').relative_to(ROOT).as_posix())
        with zipfile.ZipFile(pending) as bundle:
            if bundle.testzip() is not None:raise ValueError('Archive verification failed')
            for entry in index:
                with bundle.open(entry['path']) as stream:
                    digest=hashlib.file_digest(stream,'sha256').hexdigest()
                if digest!=entry['sha256']:raise ValueError('Archive SHA mismatch: '+entry['path'])
        with pending.open('r+b') as stream:stream.flush();os.fsync(stream.fileno())
        for attempt in range(50):
            try:pending.replace(archive);break
            except PermissionError:
                if attempt==49:raise
                time.sleep(.1)
        save(DOC/'ARCHIVE_VERIFICATION.json',{'path':str(archive.resolve()),'sha256':sha(archive),'entries':len(index)+1,'zip_crc_verified':True,'every_indexed_entry_sha256_verified':True})
    print('Published',DOC,'final' if a.final else 'checkpoint')


if __name__=='__main__':main()
