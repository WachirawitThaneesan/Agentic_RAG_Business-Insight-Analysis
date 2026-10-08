"""Replay saved judgments using verified uploaded citation addresses only.

Independent PDF reference text and saved model judgments remain unchanged.
The original audit used original PDF page numbers against subset citations;
its aggregates are retained as superseded. This replay adds no model calls.
"""
import argparse
import re
from copy import deepcopy
from pathlib import Path
from scripts.evaluate_comprehensive import load, save, sha
from scripts.audit_capture_run import read_raw_judgment
from backend.eval.comprehensive import deterministic_answer, fraction
from backend.eval.score_layers import _evidence_options, _hit_key
from backend.services.answer_capture import validate_binding
from backend.eval.contract_replay import replay_answer, summarize_replay


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'input', 'audit', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    plan = load(a.source/'plan_locked.json')
    for doc in plan['documents']:
        if sha(doc['sample_pdf'])!=doc['sample_sha256'] or sha(doc['original_pdf'])!=doc['original_sha256']:
            raise ValueError('Source PDF hash changed')
    mapping = {(d['code'], m['original_pdf_page']): m['uploaded_pdf_page']
               for d in plan['documents'] for m in d['page_map']}
    bank = load(a.input/'reference_locked.json')
    labels = load(a.input/'numeric_labels_locked.json')
    records = {r['id']: r for r in load(a.input/'paired_answers.json')}
    items = {q['id']: q for q in bank['items']}
    registry = {d['code']: d for d in bank['documents']}
    rows = load(a.audit/'details.json')
    results = []
    decisions = []
    for row in rows:
        output = a.audit/'judge_outputs'/(row['key']+'.json')
        raw_result = load(output)
        if not raw_result.get('judgment'):
            continue
        item = deepcopy(items[row['id']])
        record = records[row['id']]['arms'][row['arm']]
        old = deepcopy(row['deterministic'])
        row = deepcopy(row)
        row['deterministic'] = deterministic_answer(item, record, registry)
        # Reverse-project only emitted, bound citation addresses. Keep all
        # original evidence options, including alternatives not uploaded.
        full = record['full_result']
        citations = []
        if validate_binding(full, record['answer']):
            sources = full.get('sources', [])
            for link in full.get('claim_citations') or []:
                index = link.get('source_index')
                claim = link.get('claim_index')
                if (type(index) is int and 0 <= index < len(sources)
                    and type(claim) is int and 0 <= claim < len(full.get('answer_claims') or [])
                    and link.get('source_id') == sources[index].get('source_id')):
                    citations.append(sources[index])
        inverse = {(code, uploaded): original for (code, original), uploaded in mapping.items()}
        keys = set()
        for source in citations:
            key = _hit_key(source, [item], registry, 'source')
            keys.add((key[0], inverse[key]) if key in inverse else None)
        options = _evidence_options(item)
        relevant = set.union(*options)
        valid = {key for key in keys if key is not None}
        recall = max(len(valid & option)/len(option) for option in options)
        stated = {int(page) for page in re.findall(
            r'(?:PDF\s*(?:หน้า|p(?:age)?\.?)[\s.:]*|หน้า\s*(?:PDF)?[\s.:]*|\bp\.[\s:]?)(\d+)', record['answer'], re.I)}
        allowed = {mapping[key] for key in relevant if key in mapping}
        consistent = not stated or stated <= allowed
        row['deterministic'].update(page_citation_precision=fraction(len(valid & relevant),len(keys)),
            page_citation_recall=recall, page_citation_complete=recall==1,
            prose_page_consistent=consistent, explicit_page_citation_complete=bool(stated) and consistent and recall==1)
        fact_status=row['deterministic']['fact_status']
        row['deterministic']['strict_correct']=(fact_status=='correct' and recall==1 and consistent
            if fact_status in ('correct','incorrect') else None)
        raw = read_raw_judgment(raw_result, row)
        result = replay_answer(row, raw, record, [n for n in labels if n['id']==row['id']],
                               allow_provisional=True, citation_support_decisions=raw.get('actual_citation_audit'))
        result['arm'] = row['arm']
        results.append(result)
        decisions.append({'id': row['id'], 'arm': row['arm'],
                          'old_deterministic': old, 'mapped_deterministic': row['deterministic'],
                          'saved_judge_sha256': sha(output)})
    a.output.mkdir(parents=True, exist_ok=False)
    save(a.output/'contract_details.json', results)
    save(a.output/'address_replay.json', decisions)
    save(a.output/'contract_summary.json', {arm:summarize_replay([r for r in results if r['arm']==arm],
         n_total=len(items), n_numeric_labels=len(labels), n_total_answerable=sum(q.get('answerable',True) for q in items.values()))
         for arm in sorted({r['arm'] for r in rows})})
    save(a.output/'method_lock.json', {'source_plan_sha256': sha(a.source/'plan_locked.json'),
         'saved_judge_details_sha256': sha(a.audit/'details.json'),
         'input_reference_sha256': sha(a.input/'reference_locked.json'),
         'numeric_labels_sha256': sha(a.input/'numeric_labels_locked.json'),
         'script_sha256': sha(__file__), 'new_sdk_attempts': 0,
         'independent_reference_text_and_AI_judgments_unchanged': True,
         'actual_answers_claims_links_context_and_binding_unchanged': True,
         'correction': 'Project physical citation addresses through source-verified original/subset map; factual labels unchanged',
         'supersedes_only_address_mismatched_aggregates': str(a.audit), 'human_confirmed': False})
    print('Replayed', len(results), 'saved judgments with mapped addresses')


if __name__=='__main__':
    main()
