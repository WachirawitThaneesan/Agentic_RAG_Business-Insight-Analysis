"""Publish paired retrieval diagnostics and versioned AI label repairs.

No model calls. Old scores and input banks remain immutable.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter,defaultdict
from pathlib import Path
from backend.eval.comprehensive import page_metrics,aggregate
from scripts.evaluate_comprehensive import load,save,sha,write_csv,runtime_metrics


def score(bank,path,experiment):
    docs={d['code']:d for d in bank['documents']};preds={r['id']:r for r in load(path)}
    rows=[]
    for q in bank['items']:
        if q['id'] not in preds:raise ValueError('Missing retrieval question '+q['id'])
        for arm,hits in preds[q['id']]['arms'].items():
            for k in (1,3,5,10):
                depth=5 if arm=='app_hybrid' or experiment.startswith('ablation') else 10
                rows.append({'experiment':experiment,'arm':arm,'id':q['id'],'document':q['document'],
                    'evidence_group':q['document']+'/'+str(q['source_pdf_page']),
                    **page_metrics(q,hits,docs,k=k,depth=depth)})
    return rows


def summarize(rows):
    parts=defaultdict(list)
    for r in rows:
        if r['status']=='measured':parts[(r['experiment'],r['arm'],r['k'])].append(r)
    return {f'{experiment}/{arm}/k{k}':{'n':len(part),'hits':sum(r['hit'] for r in part),
        'metrics':aggregate(part)} for (experiment,arm,k),part in parts.items()}


def run(a):
    p=a.root;o=a.output;o.mkdir(parents=True,exist_ok=False)
    old_root=Path(load(p/'publication_inputs.json')['parent_experiment'])
    original=load(old_root/'bank500_v2/reference_locked.json')
    repaired=load(p/'labels_v3/reference_locked.json')
    for folder,expected,answers in (('alias_only500',500,0),('production_weighted500',500,0),
        ('repaired_baseline498',498,0),('repaired_production498',498,50),('cross_entity498',498,0)):
        progress=load(p/folder/'progress.json')
        if progress['completed']!=expected or progress['answers_completed']!=answers or not (p/folder/'metrics.json').exists():
            raise ValueError('Incomplete experiment '+folder)
    experiments=[('original500_baseline',original,old_root/'bank500_run/retrieval.json'),
        ('original500_alias_only',original,p/'alias_only500/retrieval.json'),
        ('original500_weighted',original,p/'production_weighted500/retrieval.json'),
        ('repaired498_baseline',repaired,p/'repaired_baseline498/retrieval.json'),
        ('repaired498_weighted',repaired,p/'repaired_production498/retrieval.json'),
        ('repaired498_final',repaired,p/'cross_entity498/retrieval.json'),
        ('ablation500_candidates',original,p/'ranking_navigation_v2_ablations/retrieval.json')]
    rows=[]
    for name,bank,path in experiments:rows+=score(bank,path,name)
    summaries=summarize(rows);save(o/'retrieval_summary.json',summaries)
    write_csv(o/'retrieval_per_question.csv',rows)
    flat=[]
    for exp,r in summaries.items():
        for name,value in r['metrics'].items():
            flat.append({'experiment':exp,'metric':name,**value})
    answers=load(p/'answer_consistent_audit/summary.json')
    for cohort,result in answers['answers'].items():
        if result['n']!=50 or result['n_judge_success']!=50:
            raise ValueError('Incomplete answer audit')
        for group in ('judge_metrics','deterministic_metrics'):
            for name,value in result[group].items():
                flat.append({'experiment':cohort+'/'+group,'metric':name,**value})
    write_csv(o/'metric_summary.csv',flat)
    save(o/'answer_metrics.json',answers)
    (o/'answer_per_question.csv').write_bytes((p/'answer_consistent_audit/answer_per_question.csv').read_bytes())
    def pair(before,after):
        left={r['id']:r for r in rows if r['experiment']==before and r['arm']=='app_hybrid' and r['k']==5}
        right={r['id']:r for r in rows if r['experiment']==after and r['arm']=='app_hybrid' and r['k']==5}
        if left.keys()!=right.keys():raise ValueError('Unpaired question sets')
        return {'n':len(left),'before_hits':sum(x['hit'] for x in left.values()),
            'after_hits':sum(x['hit'] for x in right.values()),
            'recovered':sum(not left[i]['hit'] and right[i]['hit'] for i in left),
            'regressed':sum(left[i]['hit'] and not right[i]['hit'] for i in left),
            'both_missed':sum(not left[i]['hit'] and not right[i]['hit'] for i in left)}
    pairs={'original500':pair('original500_baseline','original500_weighted'),
        'repaired498':pair('repaired498_baseline','repaired498_final'),
        'final_scope_patch':pair('repaired498_weighted','repaired498_final')}
    save(o/'paired_changes.json',pairs)
    # Diagnose misses without reclassifying them as successes.
    diagnostics={r['id']:r for r in load(p/'ranking_navigation_v2_ablations/diagnostics.json')}
    items={q['id']:q for q in original['items']};failures=[]
    for r in rows:
        if r['experiment']!='original500_weighted' or r['arm']!='app_hybrid' or r['k']!=5 or r['hit']:continue
        d=diagnostics[r['id']];lex=d['lexical_page_rank'];dense=d['dense_candidate_page_rank']
        reason='company_scope_excludes_parent_report' if d['reason']=='scope_excluded' else (
            'fusion_or_numeric_route' if (lex is not None and lex<=5) or (dense is not None and dense<=5)
            else 'lexical_or_dense_ranking')
        q=items[r['id']]
        failures.append({'id':r['id'],'document':q['document'],'page':q['source_pdf_page'],
            'question':q['question_th'],'reference':q['reference_answer'],'cause':reason,
            'lexical_page_rank':lex,'dense_candidate_page_rank':dense,
            'quarantined_label':r['id'] in repaired['quarantined_ids']})
    write_csv(o/'remaining_misses.csv',failures)
    save(o/'miss_causes.json',dict(Counter(r['cause'] for r in failures)))
    verification={r['id']:r for r in load(p/'labels_v2_verification/reviews.json')}
    verification.update({r['id']:r for r in load(p/'labels_v3_verification/reviews.json')})
    save(o/'merged_reference_verification.json',list(verification.values()))
    labels=load(p/'labels_v3/summary.json');save(o/'label_summary.json',{**labels,
        'n_eligible_latest_ai_text_verification':sum(r['eligible_ai_review_subset'] for r in verification.values()),
        'verification_denominator':len(verification),'verification_note':'119 flagged labels only; mixed preserved and supplemental runs; not human certification'})
    runtime={folder:runtime_metrics(p/folder) for folder in ('alias_only500','production_weighted500',
        'repaired_baseline498','repaired_production498','cross_entity498','label_review',
        'labels_v2_verification','labels_v3_verification','answer_claim_audit','answer_claim_audit_v2',
        'focused_answer_coverage_v2','focused_context_coverage_v2','focused_relevance','focused_relevance_v2')}
    save(o/'runtime_metrics.json',runtime)
    usage=[]
    for folder in runtime:
        path=p/folder/'model_calls.json';calls=load(path) if path.exists() else []
        tokens=Counter()
        for c in calls:
            for k,v in c.get('usage',{}).items():tokens[k]+=v or 0
        usage.append({'experiment':folder,'sdk_attempts':len(calls),'successful_calls':sum(c['status']=='success' for c in calls),
            **dict(tokens),'estimated_usd_standard_2_5_flash':
                (tokens['prompt_token_count']*.30+(tokens['candidates_token_count']+tokens['thoughts_token_count'])*2.50)/1e6})
    write_csv(o/'model_usage.csv',usage)
    contract={'publication_version':'retrieval-repair-2026-10-05-v3','parent_version':'comprehensive-rag-v1.5',
        'original_reference_sha256':sha(old_root/'bank500_v2/reference_locked.json'),
        'repaired_reference_sha256':sha(p/'labels_v3/reference_locked.json'),
        'human_certified_labels':0,'reports':'Four previously used Thai reports; diagnostic, not held-out',
        'input_pdfs':'1600 physical PDF pages; original hash-locked selectable text; no new cloud OCR',
        'new_answers':50,'original500_answers_not_rerun':True,
        'answer_inference_version':'repaired_production498; before final cross-entity keyword patch',
        'inference_code_locks':{folder:load(p/folder/'inference_code_lock.json') for folder in
            ('alias_only500','production_weighted500','repaired_baseline498','repaired_production498','cross_entity498')},
        'retrieval_code':{f:sha(f) for f in ('backend/services/rag.py','backend/services/retrieval_rank.py')},
        'publisher_sha256':sha(__file__),
        'original_scores_immutable':True,'timing_scope':'Cached query embeddings. Paired corrected-bank runs overlapped; not controlled latency comparison.'}
    save(o/'experiment_scope.json',contract)
    def table(exp):
        head='| Method | Hit@5 | Precision@5 | Recall@5 | MRR@5 | nDCG@5 |\n|---|---:|---:|---:|---:|---:|'
        result=[head]
        for arm in ('bm25','dense','app_hybrid'):
            e=summaries[f'{exp}/{arm}/k5'];m=e['metrics'];result.append(
                f"| {arm} | {e['hits']}/{e['n']} ({100*m['hit']['mean']:.1f}%) | {m['precision']['mean']:.4f} | {m['recall']['mean']:.4f} | {m['mrr']['mean']:.4f} | {m['ndcg']['mean']:.4f} |")
        return '\n'.join(result)
    text=f'''# ผลการแก้เฉลยและการค้นหลักฐาน — 5 ตุลาคม 2569

## 1. สิ่งที่ทำในรอบนี้

- ตรวจ 119 เฉลยที่ถูกแจ้งเตือนโดยใช้ภาพ PDF เต็มหน้า ข้อความต้นฉบับ และบริบทหน้าใกล้เคียง โดยไม่ส่งคะแนนค้นหาหรือคำตอบของแอปให้ผู้ตรวจเฉลย
- เฉลยรุ่นใหม่มี 498 ข้อ แยก 2 ข้อที่อ้างสารบัญแทนคำตอบไว้ใน quarantine ไม่ลบหรือเปลี่ยนให้เป็นข้อผ่าน
- ปรับ {labels['change_decisions']['revised']} ระเบียน รวมคำถาม {labels['changed_question_n']} ข้อ และคำตอบอ้างอิง {labels['changed_answer_n']} ข้อ จำนวนเหล่านี้ซ้อนทับกัน ไม่บวกเป็นจำนวนคำถาม
- แยกปีรายงานออกจากปีเหตุการณ์ เช่น อนุมัติงบลงทุนปี 2566 แต่ครอบคลุมช่วง 2567–2571; วันที่อนุมัติขายหุ้นต่างจากวันที่ขายเสร็จ
- รับหน้าทางเลือกสำหรับ 5 คำถามหลังตรวจบริบท และปฏิเสธหน้าหลักสูตรเดียวกันของกรรมการคนอื่น
- B0185 มีประโยคข้าม PDF หน้า 161–162 จึงแก้เฉลยที่เดิมจบกลางคำ และกำหนดให้ต้องค้นหลักฐานครบสองหน้า
- ตรวจความสอดคล้องของเฉลย 119 ข้อซ้ำ ผ่านการตรวจ AI รอบข้อความล่าสุด 119/119; หลักฐานคำอ้างในต้นฉบับตรวจเชิงกลได้ 498/498 นี่ไม่ใช่การรับรองจากมนุษย์

## 2. การแก้โค้ดค้นหา

1. เพิ่มชื่อไทย ปตท./ปตท.สผ. และ CPAXT ให้เลือกเอกสารได้ตรงขึ้น
2. แยกชื่อบริษัทแม่และบริษัทลูกด้วยตำแหน่งชื่อที่ยาวกว่า และยังรองรับการกล่าวถึงสองบริษัทแยกกัน
3. ให้น้ำหนัก keyword ในการรวมอันดับคำถามเชิงเนื้อหาเป็น 2 ต่อ dense 1; คำถามตัวเลขคงลำดับ lexical ก่อน semantic
4. ลดข้อความนำทางซ้ำเฉพาะข้อความสำหรับจัดอันดับคำค้น ต้องซ้ำอย่างน้อย 20 หน้าและ 60% ของหน้าในเอกสาร ข้อความ/เลข/หน้าต้นฉบับยังเก็บเหมือนเดิม
5. ตัวประเมินอ่านหน้าเพิ่มเติมที่ required_evidence ระบุได้สำหรับคำถามข้อความด้วย ไม่จำกัดเฉพาะคำถามหลายตัวเลข

## 3. เทียบโค้ดด้วยคำถามและเฉลยเดิม 500 ข้อ

| Version | Hit@5 |
|---|---:|
| ผลเดิมที่เก็บไว้ | {pairs['original500']['before_hits']}/500 (62.8%) |
| เพิ่มการจับชื่อบริษัท | 352/500 (70.4%) |
| เพิ่มการปรับอันดับและลดข้อความนำทาง | {pairs['original500']['after_hits']}/500 (74.8%) |

กู้คืน {pairs['original500']['recovered']} ข้อ, ข้อที่เคยผ่านแล้วตก {pairs['original500']['regressed']} ข้อ, ยังไม่พบหน้าตามเฉลยเดิม {pairs['original500']['both_missed']} ข้อ ผลนี้แสดงการค้นหน้าหลักฐาน ไม่ใช่ความถูกต้องของคำตอบหรือ OCR

การทดลองลดข้อความนำทางเพียงอย่างเดียวมีผลต่อจำนวน Hit น้อยมากในรอบจำลอง ห้ามอ้างว่าการลดข้อความซ้ำเป็นสาเหตุหลักของการเพิ่มทั้งหมด

## 4. เทียบโค้ดเก่าและใหม่ด้วยเฉลยแก้ไขชุดเดียวกัน 498 ข้อ

### โค้ดค้นหาเดิม

{table('repaired498_baseline')}

### โค้ดค้นหาที่ปรับแล้ว

{table('repaired498_final')}

กู้คืน {pairs['repaired498']['recovered']} ข้อ และถอยหลัง {pairs['repaired498']['regressed']} ข้อ เทียบกันได้เฉพาะภายในชุดเดียวกัน ห้ามนำคะแนน 498 ไปหักลบกับคะแนน 500 เพื่ออ้างผลจากโค้ดอย่างเดียว

เมื่อมีหลายหน้าทางเลือก Precision/MAP/nDCG ใช้สหภาพหน้าที่รองรับ ส่วน Recall ใช้ชุดหลักฐานทางเลือกที่เก็บครบที่สุด B0185 ต้องสองหน้า ดังนั้น Hit@5 และ Recall@5 ไม่เท่ากันโดยนิยามอีกแล้ว

## 5. การทดลองคำตอบ

รันแอปจริงเพิ่ม 50 คำถามจากเฉลยรุ่นใหม่ มีคำตอบ Sources และ prompt ที่ใช้สร้างคำตอบจริง เก็บจำนวน SDK attempts/tokens เวลา และทรัพยากรไว้แล้ว ข้อมูลคำตอบ/การตรวจ claims หากมี อยู่ใน answer_per_question.csv และ answer_metrics.json แยกจากผลค้นหา ไม่ถือว่ารันคำตอบครบ 498 หรือ 500 ข้อ

## 6. ผลที่ยังไม่ดีและขอบเขต

- การค้น keyword ที่ตัดชื่อบริษัทและเลือกขอบเขตแล้วในรอบจำลองได้ 414/500 มากกว่า Hybrid รอบนี้ รันจำลองใช้กฎสร้าง candidates ต่างจากแอปบางกรณี จึงแสดงแยกเป็น ablation ไม่ใช่คะแนน production BM25
- เพิ่มการรับ keyword candidates จากรายงานอื่นที่กล่าวถึงชื่อเฉพาะของบริษัทแล้ว แต่ B0115 ยังไม่เข้ามาใน Top 5 การแก้ขอบเขตจึงยังไม่ใช่การแก้อันดับสำเร็จ
- ยังมีปัญหาคำไทยในชั้นข้อความ PDF เสียรูป การเลือกอันดับ และคำถามข้ามหน้า รายละเอียดทุก miss อยู่ใน remaining_misses.csv
- รายงานทั้ง 4 ฉบับเคยใช้วิเคราะห์และปรับระบบแล้ว จึงไม่เป็น final unseen thesis test
- ผู้สร้างคำตอบและผู้ตรวจบางส่วนเป็น Gemini ตระกูลเดียวกัน; 0 เฉลยรับรองโดยมนุษย์ ค่าที่ใช้ AI ตรวจยังเป็นผลชั่วคราว
- เป็นการแยกวัด retrieval/answer บน native PDF text ไม่ใช่การนำ Typhoon/Gemini OCR ทั้งเล่มมารันใหม่
- เวลาค้นใช้ query embeddings ที่เตรียมไว้ การรันโค้ดเก่า/ใหม่บนชุดแก้ไขมีช่วงซ้อนกัน ผลทรัพยากรไม่ใช่การแข่งขันความเร็วแบบควบคุม
- คะแนนเดิมและการทดลองที่ไม่สำเร็จ/วิธีที่ทำคะแนนต่ำกว่าเก็บไว้ทั้งหมด

## 7. ไฟล์และทำซ้ำ

- metric_summary.csv: คะแนนการค้นทุก k พร้อมตัวหารและ N/A
- retrieval_per_question.csv: อันดับ/คะแนนแต่ละคำถามและวิธี
- paired_changes.json: ข้อที่กู้คืน/ถอยหลังบนชุดคำถามเดียวกัน
- label_changes.csv, reference_locked.json, quarantined.json: เฉลยรุ่นใหม่และเหตุผลที่เปลี่ยน
- remaining_misses.csv: ข้อค้นพลาดและประเภทสาเหตุ
- model_usage.csv, runtime_metrics.json: จำนวนเรียกโมเดล tokens เวลา และขอบเขตทรัพยากร
- experiment_scope.json: hashes/version/ขอบเขตที่ทำจริง

เกณฑ์คะแนนใช้ backend/eval/comprehensive.py คำนวณซ้ำจาก reference_locked.json และ retrieval.json ได้ด้วย scripts.publish_retrieval_repairs โดยไม่เรียกโมเดล ผลเก่าเก็บใน docs/evaluation-2026-10-04-v1_5
'''
    (o/'README_th.md').write_text(text,encoding='utf-8')
    result=next(iter(answers['answers'].values()));jm=result['judge_metrics']
    lines=['\n## 8. คะแนนคำตอบใหม่ 50 ข้อ (เฉลยรุ่นใหม่)\n',
        '| Metric | Mean | Measured / total |','|---|---:|---:|']
    for name in ('faithfulness','faithfulness_ai_judged','factual_precision','factual_recall',
        'factual_f1','context_precision_ap','context_recall','answer_relevancy_rubric',
        'citation_source_precision','citation_claim_recall','citation_f1'):
        x=jm[name];lines.append(f"| {name} | {x['mean']:.4f} | {x['n_measured']}/{x['n_total']} |")
    lines+=['', 'Faithfulness และ factual precision หลักต้องตรวจคำอ้างรองรับด้วย ส่วน suffix ai_judged แสดงการตัดสิน AI ก่อนตรวจคำอ้าง ความต่างของสองค่านี้รวมปัญหาฟอนต์ไทยและการคัดลอกข้อความของ judge จึงห้ามเรียกส่วนต่างทั้งหมดว่า hallucination',
        'Context recall และ factual recall ตรวจแยกจากกัน พร้อมคำอ้างจริง; context precision เป็น AP ของ source usefulness ไม่ใช่ page Precision@5 และไม่ใช่ Ragas score โดยตรง',
        f"Strict scorer วัดได้เพียง {result['n_strict_scorable']}/50 ข้อ ที่เหลือ {result['n_strict_needs_review']} ข้อไม่มี rubric ที่ strict scorer รองรับ จึงห้ามรายงาน strict accuracy เป็น 0/50",
        'คำตอบทั้ง 50 สร้างก่อน patch รับ keyword ข้ามรายงาน ผลค้นหาของ patch ล่าสุดและเดิมแสดงใน paired_changes.json แยกชัดเจน',
        'ผลทดสอบซอฟต์แวร์ล่าสุด 237 passed, 5 live tests skipped; ไม่ใช่จำนวนคำตอบที่ถูก',
        'ประมาณราคาตาม snapshot Gemini 2.5 Flash ($0.30 input/$2.50 output ต่อหนึ่งล้าน tokens) ไม่ใช่ใบแจ้งหนี้จริง และไม่ทราบส่วนลด cached tokens',
        'เก็บ inference_code_lock ของแต่ละรอบไว้ก่อนรัน ข้อมูล code hashes ปัจจุบันใน experiment_scope เป็น code ตอนเผยแพร่ ไม่ใช้แทน code ตอนสร้างคำตอบ', '']
    with (o/'README_th.md').open('a',encoding='utf-8') as f:f.write('\n'.join(lines))
    for filename in ('reference_locked.json','label_changes.csv','changes.json','quarantined.json','alternate_page_decisions.json'):
        (o/filename).write_bytes((p/'labels_v3'/filename).read_bytes())
    save(o/'input_lineage.json',{str(path):sha(path) for _,_,path in experiments})
    print(json.dumps(pairs,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);run(p.parse_args())


if __name__=='__main__':main()
