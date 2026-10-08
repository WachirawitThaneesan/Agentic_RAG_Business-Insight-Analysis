"""Package complete498 outputs only; partial cohorts cannot become a ready report."""
import argparse
from collections import Counter
from pathlib import Path
from statistics import mean

from scripts.evaluate_comprehensive import load, save, sha
from backend.eval.contract_replay import numeric_results


def write_report(output, report, run_dir, audit_dir):
    names = {
        'faithfulness': 'Faithfulness — คำตอบสอดคล้องหลักฐาน',
        'factual_precision': 'Factual precision — ข้อกล่าวอ้างถูกต้อง',
        'factual_recall': 'Factual recall — ครบข้อเท็จจริงที่ต้องตอบ',
        'context_recall': 'Context recall — หลักฐานที่ค้นพบครอบคลุมคำตอบ',
        'context_precision_ap': 'Context precision (AP) — ลำดับหลักฐานที่เกี่ยวข้อง',
        'answer_relevancy_rubric': 'Answer relevance — ตรงคำถาม',
        'actual_citation_link_precision': 'Citation precision — แหล่งที่อ้างรองรับคำตอบ',
        'actual_citation_claim_recall': 'Citation recall — ข้อกล่าวอ้างมีแหล่งรองรับ',
    }
    lines = ['# ผลประเมิน Gemini/RAG ครบ 498 คำถาม', '',
        '**ยังไม่ผ่านเป้าหมาย >80% ทุกเกณฑ์** รายงานนี้แสดงผลจริงของระบบรุ่นที่ล็อกไว้ และเปิดเผยข้อผิดพลาดทั้งหมด', '',
        f"สร้างคำตอบจริง 498/498 ข้อ; มีผลตรวจด้วย AI ที่รูปแบบใช้ได้ {report['n_valid_judgments']}/498 ข้อ; งานตรวจที่ยังผิดรูปแบบ {report['n_judge_failures']} ข้อ จำนวนผลตรวจที่ใช้ได้ไม่ใช่จำนวนคำตอบที่ถูกต้อง", '',
        'ใช้ lexical_first full agent บน 4 รายงาน เป็น development set ที่เคยใช้พัฒนา ระบบใช้ Typhoon สำหรับข้อความและ Gemini สำหรับตารางและการสร้างคำตอบ ยังไม่ใช่ unseen evaluation หรือ OCR ใหม่ครบทุกหน้ารายงาน และยังไม่มีผู้ตรวจอิสระยืนยัน', '',
        '## คะแนนคำตอบและหลักฐาน', '',
        'คอลัมน์ค่าเฉลี่ยใช้เฉพาะข้อที่วัดเกณฑ์นั้นได้ คอลัมน์ขอบล่างหารด้วย 498 เสมอ โดยให้ข้อที่ไม่มีคะแนนหรือไม่เข้าเกณฑ์เป็นศูนย์ เป็นขอบล่างเชิงอนุรักษ์ ไม่ใช่การตัดข้อที่ผิดออกหรือสร้างผลตรวจใหม่', '',
        '| เกณฑ์ | ค่าเฉลี่ยข้อที่วัดได้ | จำนวนที่วัดได้ / 498 | ขอบล่างครบ 498 |',
        '|---|---:|---:|---:|']
    for key, name in names.items():
        m = report['metrics'][key]
        macro = f"{m['macro']*100:.2f}%" if m['macro'] is not None else 'ยังไม่วัด'
        lines.append(f"| {name} | {macro} | {m['n_measured']}/498 | {m['full_cohort_conservative_lower']*100:.2f}% |")
    n = report['metrics']['strict_numeric_accuracy']
    c = report['metrics']['complete_answer_success']
    lines += ['', '## เกณฑ์ที่ยังไม่ผ่าน', '',
        f"- ตัวเลขที่ผูกค่า หน่วย บริษัท ตัวชี้วัด ปี หน้า และเงื่อนไขครบ: {n['n_correct']}/102 ความสัมพันธ์ = {n['strict_lower_bound']*100:.2f}% จากคำถามตัวเลข 94 ข้อ; ยังไม่ทราบ {n['n_unknown']} ความสัมพันธ์",
        f"- ตอบครบทุกเงื่อนไขพร้อมกัน: {c['n_pass']}/498 = {c['strict_lower_bound']*100:.2f}%; ยังไม่ทราบ {c['n_unresolved']} ข้อ (รวมงานตรวจที่ล้มเหลว)",
        '- คะแนนด้านบนเป็นค่าเฉลี่ยหลายข้อ ส่วนเกณฑ์ตอบครบกำหนดให้ทุกเงื่อนไขของแต่ละข้อผ่านพร้อมกัน จึงไม่สามารถใช้คะแนนเฉลี่ยสูงแทนความสำเร็จครบทุกเงื่อนไขได้',
        '- ชื่อบริษัท/ตัวชี้วัดตรวจตาม contract เดิม บางคำที่หมายถึงสิ่งเดียวกันอาจไม่ตรงข้อความที่ล็อกไว้ ต้องตรวจแหล่งจริงก่อนแก้เกณฑ์ ผลวินิจฉัยความหมายแยกต่างหากและไม่ถูกนับเพิ่มในรายงานนี้', '',
        '## ข้อความสำหรับนำเสนอความคืบหน้า', '',
        '“ประเมินระบบด้วยคำถามครบ 498 ข้อ และรายงานคะแนนเฉลี่ยพร้อมขอบล่างที่หารด้วยจำนวนทั้งหมด ผลด้านคำตอบและหลักฐานอยู่ในระดับสูง แต่การผูกตัวเลขกับปี บริษัท และตัวชี้วัด รวมถึงการตอบครบทุกเงื่อนไขยังต้องปรับปรุง จึงยังไม่ประกาศว่าระบบผ่าน >80% ทุกเกณฑ์”', '',
        '## หลักฐานที่ตรวจย้อนกลับได้', '',
        f"- [คะแนนและจำนวนครบทุกเกณฑ์]({(output/'metrics498.json').resolve().as_posix()})",
        f"- [ผลตัวเลขครบ 102 ความสัมพันธ์]({(output/'numeric_diagnosis102.json').resolve().as_posix()})",
        f"- [คำตอบจริงครบ 498 ข้อ]({(run_dir/'paired_answers.json').resolve().as_posix()})",
        f"- [ผลตรวจรายข้อ]({(audit_dir/'contract_details.json').resolve().as_posix()})",
        f"- [งานตรวจที่ล้มเหลวและเก็บไว้]({(output/'judge_failures_retained.json').resolve().as_posix()})", '']
    (output/'REPORT_th.md').write_text('\n'.join(lines), encoding='utf-8')


def package(a):
    manifest = load(a.run_dir/'manifest.json')
    records = load(a.run_dir/'paired_answers.json')
    bank = load(a.run_dir/'reference_locked.json')
    labels = load(a.run_dir/'numeric_labels_locked.json')
    ids = [r['id'] for r in records]
    if len(ids) != 498 or ids != manifest['selected_ids'] or set(ids) != {q['id'] for q in bank['items']}:
        raise ValueError('All498 unique locked questions must have outputs in frozen order')
    if manifest['arms'] != ['lexical_first']:
        raise ValueError('Unexpected selected system')
    for f, digest in manifest['inputs_sha256'].items():
        if sha(f) != digest:
            raise ValueError('Frozen input changed: '+f)
    for f, digest in manifest['code_sha256'].items():
        if sha(a.run_dir/'frozen_code'/f) != digest:
            raise ValueError('Frozen code snapshot changed: '+f)
    details = load(a.audit_dir/'details.json')
    replays = load(a.audit_dir/'contract_details.json')
    failures = load(a.audit_dir/'failures.json')
    if len(details) != 498 or len({r['id'] for r in details}) != 498:
        raise ValueError('All498 judge inputs/outcomes must be accounted for')
    metrics = {}
    for key in ('faithfulness', 'factual_precision', 'factual_recall', 'context_recall',
                'context_precision_ap', 'answer_relevancy_rubric'):
        vals = [r.get('claims', {}).get(key) for r in details]
        measured = [v for v in vals if v is not None]
        metrics[key] = dict(macro=mean(measured) if measured else None,
                            n_measured=len(measured), n_total=498,
                            n_not_measured=498-len(measured),
                            full_cohort_conservative_lower=sum(measured)/498,
                            full_cohort_upper=(sum(measured)+498-len(measured))/498)
    for key in ('citation_link_precision', 'citation_claim_recall'):
        measured = [r['actual_citation'][key] for r in replays if r['actual_citation'].get(key) is not None]
        metrics['actual_'+key] = dict(macro=mean(measured) if measured else None,
                                    n_measured=len(measured), n_total=498,
                                    n_not_measured=498-len(measured),
                                    full_cohort_conservative_lower=sum(measured)/498,
                                    full_cohort_upper=(sum(measured)+498-len(measured))/498)
    nums = []
    per_question = []
    for row in records:
        out = row['arms']['lexical_first']
        results = numeric_results([n for n in labels if n['id'] == row['id']], out['full_result'],
                                  out['answer'], allow_provisional=True, document_registry=bank['documents'])
        nums += [dict(id=row['id'], **n) for n in results]
        per_question.append(dict(id=row['id'], numeric=results,
            capture=out['full_result'].get('answer_capture', {}).get('status'),
            capture_errors=out['full_result'].get('answer_capture', {}).get('errors', [])))
    if len(nums) != len(labels) or len(nums) != 102:
        raise ValueError('All102 required numeric relations must be accounted for')
    correct = sum(n['correct'] is True for n in nums)
    unknown = sum(n['correct'] is None for n in nums)
    metrics['strict_numeric_accuracy'] = dict(n_correct=correct, n_required=102,
        n_unknown=unknown, strict_lower_bound=correct/102,
        measured_subset_accuracy=correct/(102-unknown) if unknown < 102 else None,
        coverage=(102-unknown)/102,
        failed_checks_nonexclusive=dict(Counter(k for n in nums for k, v in n.get('checks', {}).items() if v is False)))
    passed = sum(r['complete_answer_success'] is True for r in replays)
    metrics['complete_answer_success'] = dict(n_pass=passed, n_total=498,
        strict_lower_bound=passed/498,
        n_unresolved=sum(r['complete_answer_success'] is None for r in replays)+498-len(replays))
    generation = load(a.run_dir/'summary.json')['arms']['lexical_first']
    checks = {key: m['macro'] is not None and m['macro'] > .8 for key, m in metrics.items() if 'macro' in m}
    checks.update(strict_numeric_accuracy=correct/102 > .8,
                  complete_answer_success=passed/498 > .8,
                  capture_coverage=generation['capture_coverage'] > .8,
                  answer_coverage=generation['answer_coverage'] > .8)
    report = dict(n_unique_questions=498, n_required_numeric_relations=102, n_numeric_questions=94,
        scope='All498 used development questions; not unseen or full-report fresh OCR',
        main_system='lexical_first full agent; Typhoon prose + Gemini tables and Gemini answer generation',
        human_confirmed=False, metrics=metrics, generation=generation,
        n_valid_judgments=len(replays), n_judge_failures=len(failures),
        working_target_checks=checks,
        all_targets_gt80_proven=all(checks.values()) and not failures and unknown == 0,
        numeric_association_note='Unchanged frozen entity/measure literal checks and qrels; source-semantic limitations cannot silently become passes',
        full_cohort_lower_note='Additional conservative bound: every missing/N/A metric contributes zero across all498. Does not replace applicable-answer macro or infer new judgments.',
        evidence_sha256={str(p): sha(p) for p in (a.run_dir/'manifest.json', a.run_dir/'paired_answers.json',
            a.audit_dir/'method_lock.json', a.audit_dir/'contract_details.json')})
    save(a.output/'metrics498.json', report)
    save(a.output/'numeric_diagnosis102.json', nums)
    save(a.output/'per_question498.json', per_question)
    save(a.output/'judge_failures_retained.json', failures)
    write_report(a.output, report, a.run_dir, a.audit_dir)
    print(dict(n_unique_questions=498, n_valid_judgments=len(replays), n_judge_failures=len(failures),
               numeric_correct=correct, numeric_required=102, complete_pass=passed,
               all_targets_gt80_proven=report['all_targets_gt80_proven']))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir', 'audit-dir', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    package(p.parse_args())
