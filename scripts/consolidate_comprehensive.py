"""Publish frozen RAG scores, review flags, denominators and measured costs.

No model calls. Keeps the raw 500-question score and AI-reviewed subset
separate. Does not modify questions, answers, judgments or historical results.
"""
from __future__ import annotations
import argparse
import json
import random
from collections import Counter,defaultdict
from pathlib import Path
from scripts.evaluate_comprehensive import load,save,sha,summarize,write_csv,runtime_metrics


def pct(v):return 'N/A' if v is None else f'{v*100:.1f}%'
def metric(entry,name):return entry.get('judge_metrics',{}).get(name,{}).get('mean')
def measured(entry,name):return entry.get('judge_metrics',{}).get(name,{}).get('n_measured',0)
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+
        ['| '+' | '.join(map(str,r))+' |' for r in rows])


def bootstrap(rows,seed=20261004,n=2000):
    groups=defaultdict(list)
    for row in rows:groups[row['evidence_group']].append(row)
    keys=sorted(groups);rng=random.Random(seed);values=[]
    for _ in range(n):
        selected=[row for key in rng.choices(keys,k=len(keys)) for row in groups[key]]
        values.append(sum(r['hit'] for r in selected)/len(selected))
    values.sort()
    return {'n_groups':len(keys),'replicates':n,'seed':seed,
        'hit95_percentile':[values[int(n*.025)],values[int(n*.975)-1]],
        'scope':'Descriptive resampling of labeled pages within four known reports. Not uncertainty for unseen reports.'}


def run(args):
    b=args.root;o=args.output;o.mkdir(parents=True,exist_ok=True)
    rows=load(args.audit/'details.json');retrieval=load(args.audit/'retrieval_details.json')
    summary=summarize(rows,retrieval);save(o/'summary.json',summary)
    reviews=load(b/'reference_quality500/reviews.json')
    eligible={r['id'] for r in reviews if r['eligible_ai_review_subset']}
    filtered_r=[r for r in retrieval if r['cohort']=='Thai500_retrieval' and r['id'] in eligible]
    filtered_a=[r for r in rows if r['cohort']=='Thai500_sample50_live' and r['id'] in eligible]
    save(o/'ai_review_subset_summary.json',{'n_eligible_references':len(eligible),
        'n_sample_answers_eligible':len(filtered_a),'scores':summarize(filtered_a,filtered_r),
        'note':'Separate sensitivity analysis selected without seeing answers or rankings. Same-family AI review, not human certification.'})
    manifest=load(b/'bank500_run/reference_locked.json');items={r['id']:r for r in manifest['items']}
    write_csv(o/'reference_review.csv',[{**r,'company':items[r['id']]['document'],
        'physical_pdf_page':items[r['id']]['source_pdf_page'],'question':items[r['id']]['question_th']} for r in reviews])
    write_csv(o/'answer_per_question.csv',[{'cohort':r['cohort'],'arm':r['arm'],'id':r['id'],
        'question':r['question'],'answer':r['answer'],'judge_status':r['judge_status'],
        'context_provenance':r['context_provenance'],**r['deterministic'],**r.get('claims',{})} for r in rows])
    write_csv(o/'retrieval_per_question.csv',retrieval)
    flat=[]
    for name,entry in summary['retrieval'].items():
        for name_metric,record in entry['metrics'].items():
            flat.append({'layer':'retrieval','experiment':name,'metric':name_metric,**record})
    for name,entry in summary['answers'].items():
        for name_metric,record in entry['judge_metrics'].items():
            flat.append({'layer':'answer','experiment':name,'metric':name_metric,**record})
    write_csv(o/'metric_summary.csv',flat)
    bydoc=[];intervals={}
    for arm in ['bm25','dense','app_hybrid']:
        part=[r for r in retrieval if r['cohort']=='Thai500_retrieval' and r['arm']==arm and r['k']==5]
        intervals[arm]=bootstrap(part)
        for company in sorted({i['document'] for i in items.values()}):
            selected=[r for r in part if items[r['id']]['document']==company]
            bydoc.append({'arm':arm,'company':company,'n':len(selected),'hit':sum(r['hit'] for r in selected),
                'hit_rate':sum(r['hit'] for r in selected)/len(selected),
                'ndcg_mean':sum(r['ndcg'] for r in selected)/len(selected)})
    save(o/'page_cluster_bootstrap.json',intervals);write_csv(o/'retrieval_by_company.csv',bydoc)
    failures=[]
    for r in retrieval:
        if r['cohort']=='Thai500_retrieval' and r['arm']=='app_hybrid' and r['k']==5 and not r['hit']:
            failures.append({'type':'retrieval_target_page_miss','id':r['id'],
                'company':items[r['id']]['document'],'page':items[r['id']]['source_pdf_page'],
                'label_ai_review_eligible':r['id'] in eligible,'question':items[r['id']]['question_th']})
    for r in rows:
        d=r['deterministic'];reasons=[]
        if d.get('model_error_response'):reasons.append('model_error')
        if r['answerable']:
            if d['abstained']:reasons.append('answerable_abstention')
            if not d.get('page_citation_complete'):reasons.append('required_source_page_missing')
            if not d.get('prose_page_consistent'):reasons.append('explicit_pdf_page_mismatch')
            if d['fact_status']=='incorrect':reasons.append('deterministic_fact_check_failed')
        c=r.get('claims')
        if c:
            if c['faithfulness'] is not None and c['faithfulness']<1:reasons.append('claim_support_or_quote_unverified')
            if c['factual_recall'] is not None and c['factual_recall']<1:reasons.append('required_facts_incomplete')
            if c['answer_relevancy_rubric'] is not None and c['answer_relevancy_rubric']<1:reasons.append('response_relevance_incomplete')
        elif r['judge_status']=='judge_failed':reasons.append('judge_failed')
        if reasons:failures.append({'type':'answer_audit','key':r['key'],'reasons':reasons})
    save(o/'failures.json',failures)
    runtime={name:runtime_metrics(b/name) for name in ['live_ptt24','multi8_run','bank500_run']}
    cost=[]
    # Actual recorded attempts only; reused decisions are not counted twice.
    for p in sorted(b.rglob('model_calls.json')):
        calls=load(p);good=[r for r in calls if r.get('status')=='success']
        tin=sum((r.get('usage') or {}).get('prompt_token_count') or 0 for r in good)
        tout=sum(((r.get('usage') or {}).get('candidates_token_count') or 0)+((r.get('usage') or {}).get('thoughts_token_count') or 0) for r in good)
        cost.append({'experiment':str(p.parent.relative_to(b)),'sdk_attempts':len(calls),
            'successful_sdk_calls':len(good),'input_tokens':tin,'output_including_thinking_tokens':tout,
            'estimated_usd_undiscounted':tin*.30/1e6+tout*2.50/1e6,
            'note':'Token-based estimate, not billing statement. Cache discounts not recorded; interrupted pending requests may add unknown usage.'})
    save(o/'runtime_metrics.json',runtime);write_csv(o/'model_usage_cost_estimate.csv',cost)
    save(o/'pricing.json',{'model':'gemini-2.5-flash','checked_date':'2026-10-04',
        'source':'https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing',
        'input_usd_per_million':.30,'output_including_thinking_usd_per_million':2.50,
        'estimate_only':True,'total_recorded_experiment_estimate_usd':sum(r['estimated_usd_undiscounted'] for r in cost)})
    scope={'retrieval_questions':500,'retrieval_reports':4,'physical_pdf_pages':1600,
        'labeled_pages':124,'native_text_chunks':3194,'fresh_sample_qa':50,
        'fresh_numeric_qa':16,'fresh_negative_controls':8,'fresh_multipage_qa':8,
        'fresh_unique_questions_answered':82,'fresh_answer_outputs_across_arms':114,
        'saved_historical_answer_outputs':55,'combined_audited_outputs':len(rows),
        'human_certified_reference_questions':0,'final_unseen_report_evaluation':False}
    save(o/'evaluation_scope.json',scope)
    sections=['# รายงานผลการประเมิน RAG ฉบับขยาย 4 ตุลาคม 2569',
        'รอบนี้เพิ่มเครื่องมือวัดผลแยกการค้น ข้อเท็จจริง หลักฐาน การอ้างอิง และทรัพยากร พร้อมรันการค้นจริง 500 คำถามภาษาไทย การสร้างคำตอบจริงครอบคลุม 82 คำถามใหม่ รวม 114 คำตอบเมื่อรวมสองวิธีในบางชุด ไม่ใช่การวัดคำตอบครบ 500 ข้อ และยังไม่ใช่ผลสอบกับรายงานที่ไม่เคยใช้พัฒนา',
        '## 1 ขอบเขตและที่มาของเฉลย',
        table(['รายการ','จำนวน','ความหมาย'],[
            ['รายงานไทย','4 เล่ม 1600 หน้า','PTT PTTEP CP Axtra EGCO ปีรายงาน 2567'],
            ['คลังคำถาม','500 ข้อ 124 หน้าหลักฐาน','PTT 133 PTTEP 103 CP Axtra 153 EGCO 111'],
            ['ข้อความอ้างอิงตรง PDF','500/500','ตรวจ hash และช่วงข้อความ ไม่รับรองความหมายของเฉลย'],
            ['AI ตรวจเฉลยรอบที่สอง',f'{len(eligible)}/500 ผ่าน',f'{500-len(eligible)} ข้อทำเครื่องหมายให้ตรวจเพิ่ม'],
            ['คำตอบชุดกว้าง','50 คำถาม','เลือกดัชนีห่างเท่ากันจากชุดที่สลับบริษัท ไม่เลือกตามคะแนน'],
            ['ตรวจตัวเลขและปฏิเสธ','16 + 8 คำถาม','รันแอปและ BM25 รวม 48 คำตอบ'],
            ['หลายหน้าและหลายบริษัท','8 คำถาม','รันสองวิธีรวม 16 คำตอบ']]),
        'AI สร้างคำถามจาก PDF ต้นฉบับและผูกกับช่วงข้อความจริงก่อนรันค้น เฉลยไม่ใช้คำตอบของระบบหรือผลค้นเป็นแหล่งอ้างอิง แต่ AI ผู้สร้าง ผู้ตอบ และผู้ตรวจเป็นตระกูล Gemini จึงมีความเสี่ยงร่วม ไม่เทียบเท่าการตรวจอิสระโดยมนุษย์ การตรวจรอบที่สองไม่เห็นคำตอบหรืออันดับค้นและไม่แก้เฉลยเดิม',
        'ข้อที่ถูกทำเครื่องหมายซ้อนกันได้ เช่น ปีไม่ชัด 87 ข้อ ข้อความจากฟอนต์อ่านยาก 27 ข้อ คำตอบอ้างอิงรองรับไม่ครบ 21 ข้อ บริษัทไม่ตรง 7 ข้อ และตอบจากหลักฐานไม่ได้ 10 ข้อ ผลทั้ง 500 ข้อยังคงอยู่ ผล 381 ข้อที่ผ่าน AI review เป็น sensitivity analysis แยกไฟล์ ไม่ใช้แทนผลเดิม',
        'พบ 8 คำถามมีช่วงข้อความซ้ำบนหน้าอื่น เก็บหน้าทางเลือกไว้ให้ตรวจเพิ่ม ยังไม่เปลี่ยน qrels อัตโนมัติ หน้าอื่นที่รองรับได้จริงอาจถูกนับเป็น miss ตามเฉลยปัจจุบัน',
        '## 2 ขั้นตอนและเครื่องมือ',
        '1. ล็อก PDF เฉลย คำถาม และ hash ก่อนค้น\n2. อ่าน native text และสร้าง 3194 chunks จาก 1600 หน้า รอบนี้ไม่ได้ผ่าน OCR ใหม่\n3. BM25 ใช้ PyThaiNLP newmm; dense ใช้ bge-m3 ผ่าน Ollama และ PostgreSQL; hybrid ใช้โค้ดค้นจริงของแอป\n4. ใช้ corpus เดียวกัน เก็บ BM25/dense 10 อันดับ และ hybrid 5 อันดับ ไม่มีเฉลยหรือหน้าเป้าหมายส่งให้ตัวค้น\n5. ใช้ agent จริงกับ Gemini 2.5 Flash สำหรับคำตอบแอป และ baseline BM25 กับโมเดลเดียวกันในชุดตัวเลข/หลายหน้า\n6. เก็บ prompt หลักฐานที่ส่งให้โมเดลจริง คำตอบ sources SDK attempts token เวลา RSS และ GPU ที่วัดได้\n7. ตัวตรวจ deterministic ตรวจค่า เครื่องหมาย ปี หน่วย สเกล และหน้า ส่วน custom AI judge แยก atomic claims และอ้างช่วงข้อความให้ตรวจย้อนกลับ\n8. ตัวตรวจความตรงคำถามรอบที่สองเห็นเฉพาะคำถามกับคำตอบ เพื่อไม่ให้คุณภาพ context ปนกับคะแนน response relevance',
        'ใช้ฐานข้อมูล PostgreSQL และ DuckDB แยกสำหรับการทดลอง ไม่เขียนข้อมูล production ไม่มีการปรับ ranking หรือคำตอบระหว่างรอบนี้ ใช้ vectors ที่ตรวจ fingerprint และ query vectors จากคำถามจริงเพื่อประหยัดเวลา ผล retrieval timing จึงไม่รวมการสร้าง embedding ของ query แบบออนไลน์ทุกครั้ง',
        '## 3 ผลการค้นหลักฐาน 500 คำถาม',
        table(['วิธี','Hit@5','Precision@5','Recall@5','MRR@5','nDCG@5'],[
            [arm]+[pct(summary['retrieval'][f'Thai500_retrieval/{arm}@5']['metrics'][m]['mean']) for m in ['hit','precision','recall','mrr','ndcg']]
            for arm in ['bm25','dense','app_hybrid']]),
        'แอปพบหน้าเป้าหมาย 314/500 ข้อ BM25 271/500 และ dense 195/500 ชุดนี้แต่ละข้อระบุหน้าหลักฐานหนึ่งหน้า จึงทำให้ Hit@5 เท่ากับ Recall@5 โดยโครงสร้างเฉลย Precision@5 สูงสุดได้ 20% หากหน้าที่เกี่ยวข้องมีหนึ่งหน้าในห้าผลลัพธ์ คะแนน 12.56% จึงไม่ใช่ความแม่นยำของคำตอบ',
        'หลังกรองเฉพาะ 381 เฉลยที่ AI ตรวจผ่าน แอปพบหน้า 239/381 หรือ 62.73% BM25 207/381 หรือ 54.33% และ dense 146/381 หรือ 38.32% แนวโน้มคล้ายทั้งชุด ค่าช่วงความเชื่อมั่นจาก bootstrap ตามกลุ่มหน้าเป็นคำอธิบายความแปรผันภายในสี่รายงานเท่านั้น ไม่ใช้อนุมานเอกสารใหม่',
        'บันทึก Hit Precision Recall F1 MRR MAP nDCG และหลักฐานครบ ที่ k 1 3 5 10 โดย hybrid@10 เป็น N/A เพราะเก็บเพียง 5 อันดับ ผลซ้ำกินอันดับและไม่รับเครดิตความเกี่ยวข้องซ้ำ การค้นว่างนับเป็น miss; ไม่มีตัวหารไม่แสดง 0/0',
        '## 4 ผลคำตอบและหลักฐานแยกตามชุด',
        table(['ชุดและวิธี','จำนวนคำตอบ','Faithfulness ตรวจ quote','Factual F1','Response relevance'],[
            [name,str(e['n']),pct(metric(e,'faithfulness'))+f' (n={measured(e,"faithfulness")})',pct(metric(e,'factual_f1'))+f' (n={measured(e,"factual_f1")})',pct(metric(e,'answer_relevancy_rubric'))+f' (n={measured(e,"answer_relevancy_rubric")})']
            for name,e in summary['answers'].items()]),
        'ตัวเลขตารางเป็นค่าเฉลี่ยรายคำตอบจากข้อที่วัดได้เท่านั้น คำตอบปฏิเสธที่ไม่มี claim มี Faithfulness เป็น N/A จึงรายงาน answer coverage และ abstention แยก ห้ามตีความค่าเฉลี่ยที่ไม่รวมข้อไม่มี claim เป็นความสำเร็จทุกคำถาม',
        'Faithfulness มีสองค่าในไฟล์: faithfulness_ai_judged เป็นการตัดสิน entailment ของ AI; faithfulness เป็นคะแนนที่ตรวจว่าช่วง quote พบจริงด้วย กรณี AI อ้างข้อความไม่ตรงจะถูกลดเป็น insufficient จึงเป็นค่าระมัดระวังและปนความสามารถคัด quote ของ judge ไม่ควรเรียกทุกข้อที่ถูกลดคะแนนว่าระบบ hallucinate ฟอนต์ไทย/ช่องว่างปรับเทียบแบบอนุรักษ์และบันทึก offset กลับไปข้อความเดิม โดยไม่ลบเครื่องหมาย ตัวเลข หรือหน่วย',
        'คำตอบข้อความไม่ใช้การเทียบประโยคตรงตัว ตัวตรวจ numeric ไม่สามารถตัดสิน prose จะเป็น needs_review ไม่ถูกนับเป็น 0% accuracy; ใช้ factual claim precision recall F1 แทน ส่วนข้อที่ judge ล้มเหลวหรือไม่มี context เป็น N/A และรายงานจำนวนแยก',
        '## 5 หลักฐานหลายหน้าและการตอบเมื่อไม่มีข้อมูล',
        table(['วิธีหลายหน้า','Hit@5','Recall@5','หลักฐานครบ@5','ตัวเลขครบ','ค่าและหน้าเข้มงวด'],[
            [arm,pct(summary['retrieval'][f'Multipage8_live/{search}@5']['metrics']['hit']['mean']),
             pct(summary['retrieval'][f'Multipage8_live/{search}@5']['metrics']['recall']['mean']),
             pct(summary['retrieval'][f'Multipage8_live/{search}@5']['metrics']['complete_evidence']['mean']),
             f'{summary["answers"][f"Multipage8_live/{arm}"]["numeric_accuracy"]["n_correct"]}/8',
             f'{summary["answers"][f"Multipage8_live/{arm}"]["strict_correct"]}/8']
            for arm,search in [('app_gemini','app_hybrid'),('bm25_gemini','bm25')]]),
        'แอปพบอย่างน้อยหนึ่งหน้าสำหรับ 5/8 ข้อ แต่ได้หลักฐานครบสองหน้าหรือสองบริษัทเพียง 3/8 ข้อ นี่เป็นตัวอย่างจริงว่าคะแนน Hit ไม่แทน Recall และไม่รับรองว่าตอบครบ ตัวตรวจหลายค่าบังคับพบทุกค่าที่กำหนด ส่วนการผูกชื่อรายการกับบริษัทใช้ claim judge แยก',
        'ชุดตัวเลขเดี่ยว 16 ข้อ: แอปค่าและหน้าเข้มงวด 14/16; BM25 11/16 ก่อนตรวจข้อความเลขหน้าแอปเคยได้ 15/16 แต่ F05 ระบุ PDF หน้า 6 ทั้งที่หลักฐานจริงเป็นหน้า 5 จึงไม่ผ่านเกณฑ์ใหม่ ผลเก่าคงไว้ไม่เขียนทับ',
        'คำถามไม่มีข้อมูล 8 ข้อเป็นการถามปีรายงานที่ไม่มีใน corpus และกำชับไม่ใช้ปี 2567 แทน แอปปฏิเสธเหมาะสม 8/8 ข้อ ต้องอ่านร่วมกับ false abstention ในคำถามที่มีคำตอบ ไม่พิสูจน์ unanswerable ทุกรูปแบบ',
        '## 6 นิยามตัววัดที่ใช้',
        table(['ตัววัด','หลักการและตัวหาร'],[
            ['Hit@k','จำนวนคำถามที่เจออย่างน้อยหนึ่งหน้าที่เกี่ยวข้อง / คำถามทั้งหมด'],
            ['Page precision@k','หน้าที่เกี่ยวข้องไม่ซ้ำใน k อันดับ / k; ผลซ้ำไม่ได้เครดิตเพิ่ม'],
            ['Page recall@k','หน้าที่ต้องใช้ซึ่งค้นได้ / หน้าที่ต้องใช้; เลือกชุดหน้าทางเลือกที่ครบที่สุด'],
            ['MRR MAP nDCG','MRR ให้น้ำหนักหน้าถูกแรก; MAP วัดอันดับของหน้าที่เกี่ยวข้อง; nDCG เทียบอันดับอุดมคติ'],
            ['Faithfulness','claim ที่ actual context รองรับ / factual answer claims'],
            ['Factual precision recall F1','precision ตรวจ claim คำตอบกับ PDF/เฉลย; recall ตรวจ required facts ครบ; F1 สมดุลสองค่า'],
            ['Context precision AP','average precision ของ contexts ที่มีประโยชน์ตามลำดับ ไม่เท่ากับ Page precision'],
            ['Context recall','required reference claims ที่ context รองรับ / required claims ทั้งหมด'],
            ['Response relevance','rubric 0 ไม่ตรงหรือไม่ตอบ 1 ตอบบางส่วน/มีส่วนเกิน 2 ตรงครบ; หาร 2 เป็น 0–1'],
            ['Claim relevance precision','claim ที่จำเป็นต่อคำถาม / claims ในคำตอบ'],
            ['Citation precision recall F1','precision แหล่งอ้างที่รองรับ claim / แหล่งที่ส่ง; recall claims มี source รองรับ / claims'],
            ['Page citation accuracy','หน้าใน source links และเลขหน้าในข้อความต้องตรง physical PDF qrels'],
            ['Abstention precision recall F1','precision ปฏิเสธถูก / ปฏิเสธทั้งหมด; recall ปฏิเสธถูก / ข้อไม่มีคำตอบ'],
            ['Coverage และ selective accuracy','สัดส่วนข้อที่ตอบ / ข้อมีคำตอบ; accuracy เฉพาะข้อที่ตอบและ scorer ตัดสินได้'],
            ['Complete answer success','ทุก claim ต้องมีหลักฐาน ถูก ตรงคำถาม อ้างอิงได้ required facts ครบ และ numeric/page checks ผ่าน'],
            ['Latency SDK calls tokens RSS GPU','เวลาแต่ละคำถาม attempts รวม retry token จริง และทรัพยากรที่ sampler วัดได้']]),
        'นิยามอิงงานประเมิน RAG และ BEIR แต่ implementation นี้เป็น custom scorer และ custom Gemini judge ไม่ใช่การรันไลบรารี Ragas โดยตรง Context/citation scores ใช้ sources ของแอปตามลำดับ และตรวจ claim-level support โดยไม่ต้องมี inline citation ทุกประโยค มี source links รองรับก็รับได้',
        '## 7 เวลา การเรียกโมเดลและทรัพยากร',
        table(['รอบ','Wall seconds','Runner peak MiB','GPU total peak MiB'],[
            [name,f'{record["wall_seconds"]:.2f}',f'{record["runner_peak_rss_mib"]:.2f}',str(record['gpu_peak_total_used_mib'])] for name,record in runtime.items()]),
        'ชุดกว้าง 500 retrieval และ 50 answers ใช้รวม 1042.81 วินาที แอปสร้างคำตอบ 50 calls สำเร็จจาก 51 SDK attempts ใช้ input 321799 และ output 5940 tokens; median 2.90 วินาที p95 5.51 วินาทีต่อ app query รวมเวลารอ/ค้น/ตอบตาม runner ไม่ใช่ controlled latency benchmark',
        'Runner RSS ไม่รวม RAM ทั้งระบบหรือ PostgreSQL Docker; Ollama เก็บแยกแต่ shared pages อาจนับซ้ำ GPU เป็นการใช้งานทั้งอุปกรณ์รวมแอปอื่น ไม่ใช่ VRAM ของโปรเจกต์โดยเฉพาะ งาน judge บางส่วนรันคู่ขนาน การประมวลผล cloud ไม่สามารถวัด RAM/GPU จากเครื่องผู้ใช้ได้',
        f'ต้นทุนประมาณจาก token ที่บันทึกทั้งหมดในรอบนี้รวมการร่างเฉลย retries และ judge อยู่ที่ US${sum(r["estimated_usd_undiscounted"] for r in cost):.4f} ตาม standard Gemini 2.5 Flash input $0.30 และ output/thinking $2.50 ต่อหนึ่งล้าน tokens ตรวจราคา 4 ต.ค. 2569 ไม่ใช่ยอดบิลจริง ไม่รวมส่วนลด cache ที่ไม่ได้เก็บ และอาจขาด usage ของคำขอที่ถูกยกเลิกค้างไว้ แต่ละ experiment แยกใน model_usage_cost_estimate.csv',
        '## 8 OCR และผลการทำงานที่มีอยู่เดิม',
        table(['การทดลองเดิม','ผลที่เก็บไว้','ขอบเขต'],[
            ['Typhoon OCR cache','13/16 เซลล์ กราฟ 4 ข้อยัง unscored','เก่า ไม่ใช่ mixed pipeline ล่าสุด'],
            ['Typhoon text และ Gemini table','16/16 เซลล์ 9/12 วลี 1/4 กราฟ','ชุด 32 หน้าเล็ก'],
            ['Docling TableFormer EasyOCR','10/16 เซลล์ 7/12 วลี 0/4 กราฟ','32 หน้า CPU 2742.93 วินาที peak 4908 MB'],
            ['Offline scanned PDF','5/5 หน้า index 0/1 คำตอบ','584.20 วินาที peak 4832.1 MiB'],
            ['Docling long OCR','220/220 หน้า หยุด 110 ต่อ 111 จบ','13318.1 วินาที OCR/checkpoint ไม่รวม Q&A'],
            ['Thai PDF discovery','17/20 เว็บไซต์เป้าหมาย','อัตราค้นพบไฟล์ ไม่ใช่ answer accuracy'],
            ['Regression tests ล่าสุด','229 ผ่าน 5 live tests ข้าม','ตรวจโค้ด ไม่ใช่คะแนนเอกสาร']]),
        'รอบใหม่ยังไม่ได้วัด CER/WER ทั้งหน้า หรือทดสอบการอ่าน Typhoon/Gemini ใหม่ครบ 500 คำถาม กราฟ ตารางซับซ้อน และ private offline quality ยังมีช่องว่าง จึงนำผล OCR เก่ามาประกอบแยกชุด ไม่เติมคะแนนที่ไม่เคยวัด',
        '## 9 การตรวจความน่าเชื่อถือของ scorer',
        'Regression ตรวจตัวเลขผิดเครื่องหมาย ปี หน่วย สเกล หน้าผิด หลายค่าต้องครบ ผลซ้ำใน ranking ไม่มีตัวหาร และ quote ปลอม ชุดควบคุม judge 10 กรณีตรวจ faithfulness ตามทิศทางได้ 9/9 กรณีที่มี claim ส่วนคำตอบปฏิเสธอีกข้อเป็น N/A; นี่เป็น sanity check สังเคราะห์ ไม่ใช่ calibration จากมนุษย์',
        'พบว่า joint judge ให้ response relevance สูงเกินไปเมื่อใส่กำไรเพิ่มในคำถามรายได้ จึงแยก response-only judge และบันทึกคะแนนเดิมไว้ ตัวตรวจใหม่ลดกรณีนั้นเป็น 1/2 อย่างไรก็ตาม AI ยังตัดสินบางกรณีไม่คงที่ เช่นไม่พูดชื่อบริษัทซ้ำ หรือให้ refusal ผ่านทั้งที่ ANSWERABLE=true จึงใช้กฎ deterministic ให้คำตอบว่าง/ปฏิเสธที่ไม่มี claim ได้ relevance 0 ในข้อที่ตอบได้ และเปิดเผยคำตัดสิน AI เดิม',
        'ตรวจพบ joint judge สับสน answer coverage กับ context coverage จึงรันผู้ตรวจ coverage แยกสองงาน: ผู้ตรวจคำตอบไม่เห็น context และผู้ตรวจ context ไม่เห็นคำตอบ ทั้งสองเห็น required reference claims ชุดเดียวกัน ตรวจกรณีควบคุมได้ 10/10 ด้าน answer coverage และ 10/10 ด้าน context coverage หลังแยก มี raw outputs และ quote offsets เก็บไว้ ผล synthetic controls ที่ใช้พัฒนาผู้ตรวจไม่ใช่ independent validation',
        'citation ไม่รับ source quote เป็นหลักฐานรองรับเมื่อ verdict บอกว่าตัว claim ขัดกับ context แม้ quote จะพบจริง การปฏิเสธใน negative controls ที่ถามตัวเลขต้องมี refusal marker และไม่มีตัวเลขคำตอบอื่นนอกปี/เลขหน้า คำอธิบายว่ามีเฉพาะรายงานปีใดรับได้ จึงไม่ให้คำตอบที่บอกไม่มีข้อมูลแต่แถมตัวเลขผ่านเอง ส่วน coverage ของ positive ใช้ regex marker แบบระมัดระวัง คำตอบที่ทั้งตอบบางส่วนและปฏิเสธอีกส่วนอาจต้องทวนด้วยมนุษย์',
        'ข้อจำกัดอื่น: quote พบจริงไม่ได้พิสูจน์ entailment ด้วยตัวเอง; judge อาจรวมหลาย claim เป็นประโยคเดียว; semantic correctness ของเฉลยต้องมีผู้ตรวจอิสระ; AI judge failures ต้องเป็น N/A ไม่ใช่คำตอบผิด รูปแบบ JSON ที่ตอบยาวจนถูกตัดเก็บ raw failures แล้ว retry ในรุ่นแยก',
        '## 10 ข้อสรุปและงานถัดไป',
        'เครื่องมือวัดผลครอบคลุมหลายชั้นและมีผลจริงครบ 500 retrieval พร้อม sampled answers และ negative/multipage probes แต่ยังไม่รับรองว่าคุณภาพโมเดลหรือเฉลยสมบูรณ์ ผลกว้างชี้ว่าการค้นยังเป็นคอขวด: hybrid miss 186/500 ข้อ และการรวมหลักฐานหลายหน้าขาดบ่อย',
        'ลำดับถัดไป: 1 ตรวจ 119 labels และหน้าทางเลือกโดยมนุษย์ โดยยังไม่เปิดคะแนน 2 ตรวจ retrieval misses ที่ labels ผ่านก่อนปรับ ranking 3 แก้ multi-page/company evidence aggregation และเลขหน้าในคำตอบ 4 ตรวจ claim judge กับ human-reviewed sample แล้วล็อก rubric 5 ขยาย answer generation ให้ครบ 500 หลังปัญหาสำคัญลดลง 6 สอบกับรายงานไทยใหม่ทั้งเล่มที่ไม่เคยใช้พัฒนา พร้อม pipeline OCR จริงและ offline แยก',
        '## 11 ไฟล์ผลและการรันซ้ำ',
        'summary.json เก็บทุก metric และ denominator; metric_summary.csv ตารางคะแนน; retrieval_per_question.csv และ answer_per_question.csv ผลรายข้อ; reference_review.csv flags; failures.json รายการไม่ผ่าน; ai_review_subset_summary.json ผล subset; runtime_metrics.json และ model_usage_cost_estimate.csv ทรัพยากรและประมาณราคา; raw inputs/outputs และ method locks อยู่ในโฟลเดอร์ experiment ที่รายงาน README ระบุไว้',
        'ผลเก่าไม่ถูกเขียนทับ คะแนนใหม่เปลี่ยน VERSION ตามวิธีตรวจ การ reuse ตรวจ payload และ instruction hash ก่อนรับคำตัดสินเดิม เก็บ raw JSON และ lineage hash การล็อก code ของ large retrieval เป็นบันทึกหลังรัน ไม่อ้างว่า preregistered; ไฟล์ input/PDF/vectors ล็อกก่อนรันแล้ว',
        '## 12 แหล่งอ้างอิงหลัก',
        '- Faithfulness: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/\n- Factual correctness: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/\n- Context precision: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/\n- Context recall: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/\n- Answer relevancy: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/\n- BEIR metrics: https://github.com/beir-cellar/beir/wiki/Metrics-available\n- Gemini pricing: https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing'
    ]
    (o/'evaluation_report_th.md').write_text('\n\n'.join(sections)+'\n',encoding='utf-8')
    save(o/'input_lineage.json',{'audit':str(args.audit),'audit_details_sha256':sha(args.audit/'details.json'),
        'audit_retrieval_sha256':sha(args.audit/'retrieval_details.json'),'reference_review_sha256':sha(b/'reference_quality500/reviews.json'),
        'publisher_code_sha256':sha(Path(__file__)),'method_version':summary['method_version']})
    print(json.dumps(scope,ensure_ascii=False,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())

if __name__=='__main__':main()
