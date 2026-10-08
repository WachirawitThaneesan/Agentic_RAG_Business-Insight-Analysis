"""Apply previously PDF-reviewed alternate pages to single-relation qrels.

Do not use application retrieval or answers. Multiple-quantity questions keep
their existing AND evidence contract rather than receiving a guessed union.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from scripts.evaluate_comprehensive import load, save, sha


def freeze(reference, labels_path, output):
    if output.exists(): raise ValueError('Preserve previous bank versions')
    original = load(reference)
    bank = deepcopy(original)
    labels = load(labels_path)
    changed = []
    for item in bank['items']:
        selected = [n for n in labels if n['id'] == item['id']]
        if len(selected) != 1 or item.get('required_evidence') or item.get('evidence_options'):
            continue
        label = selected[0]
        if label.get('blind_recheck_reference_conflict') or not label.get('identity_review_sha256'):
            continue
        alternatives = label.get('alternate_pdf_pages', [])
        if not alternatives: continue
        item['evidence_options'] = [[{'document': item['document'], 'source_pdf_page': p}]
            for p in sorted(set([item['source_pdf_page']] + alternatives))]
        changed.append({'id': item['id'], 'evidence_options': item['evidence_options'],
            'source_only_review_sha256': label['identity_review_sha256']})
    output.mkdir(parents=True)
    save(output/'reference_locked.json', bank)
    save(output/'numeric_labels_locked.json', labels)
    save(output/'change_log.json', {'reference_parent_sha256': sha(reference),
        'numeric_labels_parent_sha256': sha(labels_path), 'changes': changed,
        'question_texts_unchanged': [q['question_th'] for q in original['items']] == [q['question_th'] for q in bank['items']],
        'application_predictions_used': False, 'human_confirmed': False,
        'policy': 'Only single-relation alternatives explicitly supported by previous source-only PDF review'})
    print('Frozen', len(changed), 'previously reviewed evidence alternatives')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--labels', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    freeze(a.reference, a.labels, a.output)
