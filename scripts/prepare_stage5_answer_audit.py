"""Create evaluation-only views of actual saved ingestion answers.

Only filename and citation-address labels are projected through the verified
subset map. Original answers, context, claims, links and binding stay intact.
No evaluation reference is supplied to generation or ingestion.
"""
import argparse
from copy import deepcopy
from pathlib import Path
from scripts.evaluate_comprehensive import load, save, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'repaired', 'reference', 'labels', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    plan = load(a.source/'plan_locked.json')
    bank = load(a.reference)
    labels = load(a.labels)
    original = load(a.source/'answers.json')
    repaired = load(a.repaired/'answers.json')
    ids = [q['id'] for q in plan['questions']]
    if [r['id'] for r in original] != ids or [r['id'] for r in repaired] != ids:
        raise ValueError('Actual answer selection differs')
    mapping = {}
    filenames = {}
    for doc in plan['documents']:
        if sha(doc['sample_pdf']) != doc['sample_sha256'] or sha(doc['original_pdf']) != doc['original_sha256']:
            raise ValueError('Source hash changed')
        uploaded = load(a.source/f"upload_{doc['code']}.json")
        filenames[doc['code']] = uploaded['filename']
        for page in doc['page_map']:
            mapping[(doc['code'], page['original_pdf_page'])] = page['uploaded_pdf_page']
    view = deepcopy(bank)
    view['items'] = [q for q in view['items'] if q['id'] in ids]
    for doc in view['documents']:
        doc['source_file'] = filenames[doc['code']]
    projected = []
    address_log = []
    for label in labels:
        if label['id'] not in ids:
            continue
        key = (label['document'], label['source_pdf_page'])
        if key not in mapping:
            raise ValueError('Required numeric source outside uploaded scope')
        new = deepcopy(label)
        new['source_pdf_page'] = mapping[key]
        new['alternate_pdf_pages'] = [mapping[(label['document'], page)] for page in label.get('alternate_pdf_pages', [])
                                      if (label['document'], page) in mapping]
        allowed = ('source_pdf_page', 'alternate_pdf_pages')
        assert {k:v for k,v in new.items() if k not in allowed} == {k:v for k,v in label.items() if k not in allowed}
        projected.append(new)
        address_log.append({'id': label['id'], 'quantity_index': label['quantity_index'],
                            'original_page': label['source_pdf_page'], 'uploaded_page': new['source_pdf_page']})
    a.output.mkdir(parents=True, exist_ok=False)
    paired = [{'id': old['id'], 'arms': {'original_ingested': old, 'repaired_ingested': new}}
              for old, new in zip(original, repaired)]
    save(a.output/'paired_answers.json', paired)
    save(a.output/'reference_locked.json', view)
    save(a.output/'numeric_labels_locked.json', projected)
    save(a.output/'address_projection.json', address_log)
    save(a.output/'projection_lock.json', {
        'source_plan_sha256': sha(a.source/'plan_locked.json'),
        'original_answers_sha256': sha(a.source/'answers.json'),
        'repaired_answers_sha256': sha(a.repaired/'answers.json'),
        'original_reference_sha256': sha(a.reference), 'original_numeric_labels_sha256': sha(a.labels),
        'script_sha256': sha(__file__), 'new_sdk_attempts': 0,
        'reference_pdf_pages_remain_original': True,
        'factual_tuples_and_scorer_unchanged': True,
        'actual_outputs_and_binding_unchanged': True,
        'scope': '16 saved actual ingestion answers; structural/factual comparison of application repair; not OCR ablation or 50-pair gate',
        'human_confirmed': False})
    print('Prepared', len(paired), 'pairs and', len(projected), 'numeric tuples')


if __name__ == '__main__':
    main()
