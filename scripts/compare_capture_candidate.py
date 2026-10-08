"""Compare first saved candidate outcomes with a frozen baseline; no cloud calls."""
import argparse
from collections import Counter

from backend.eval.contract_replay import numeric_results, summarize_replay
from scripts.evaluate_comprehensive import load, save, sha
from scripts.run_capture_paired import summarize


def compare(a):
    baseline = load(a.baseline_run/'paired_answers.json')
    candidate = load(a.candidate_run/'paired_answers.json')
    ids = [r['id'] for r in candidate]
    manifest = load(a.candidate_run/'manifest.json')
    if ids != manifest['selected_ids']:
        raise ValueError('Candidate selection incomplete or changed')
    base_manifest = load(a.baseline_run/'manifest.json')
    for key in ('alternative_corpus_sha256', 'pdfs_sha256'):
        if base_manifest[key] != manifest[key]:
            raise ValueError('Different frozen corpus/PDFs')
    for f in ('reference_locked.json', 'numeric_labels_locked.json'):
        if sha(a.baseline_run/f) != sha(a.candidate_run/f):
            raise ValueError('Different locked reference/labels')
    if load(a.baseline_run/'model_configuration.json') != load(a.candidate_run/'model_configuration.json'):
        raise ValueError('Model configuration changed')
    selected = [r for r in baseline if r['id'] in set(ids)]
    if len(selected) != len(ids):
        raise ValueError('No complete saved baseline selection')
    labels = load(a.candidate_run/'numeric_labels_locked.json')
    bank = load(a.candidate_run/'reference_locked.json')
    answerable = {q['id'] for q in bank['items'] if q['id'] in ids and q.get('answerable', True)}
    arms = manifest['arms']
    n_numeric = sum(l['id'] in ids for l in labels)
    result = {'scope': 'Development saved baseline vs first candidate outputs; unchanged gold/scorer, same corpus/model/ranking; historical baseline time/randomness not counterbalanced',
              'n_questions': len(ids), 'n_required_numeric_tuples': n_numeric,
              'human_confirmed': False, 'new_cloud_calls': 0, 'arms': {},
              'input_sha256': {str(p): sha(p) for p in [a.baseline_run/'manifest.json',
                  a.baseline_run/'paired_answers.json', a.candidate_run/'manifest.json',
                  a.candidate_run/'paired_answers.json', a.baseline_audit/'contract_details.json',
                  a.candidate_audit/'contract_details.json']}}
    generation = {tag: summarize(rows, labels, bank['documents'], len(ids), planned_ids=ids,
                    arms=arms, answerable_ids=answerable)
                  for tag, rows in [('baseline', selected), ('candidate', candidate)]}
    audits = {tag: [r for r in load(folder/'contract_details.json') if r['id'] in ids]
              for tag, folder in [('baseline', a.baseline_audit), ('candidate', a.candidate_audit)]}
    transitions = []
    for arm in arms:
        output = {}
        numeric_maps = {}
        for tag, records in [('baseline', selected), ('candidate', candidate)]:
            measured = []
            for record in records:
                saved = record['arms'][arm]
                measured += [dict(id=record['id'], **n) for n in numeric_results(
                    [l for l in labels if l['id'] == record['id']], saved['full_result'], saved['answer'],
                    allow_provisional=True, document_registry=bank['documents'])]
            numeric_maps[tag] = {(r['id'], r['quantity_index']): r for r in measured}
            output[tag] = {'generation': generation[tag]['arms'][arm],
                'audit': summarize_replay([r for r in audits[tag] if r['arm'] == arm],
                    n_total=len(ids), n_numeric_labels=n_numeric, n_total_answerable=len(answerable)),
                'numeric_correct_required': sum(n['correct'] is True for n in measured),
                'numeric_required': n_numeric, 'numeric_unknown': sum(n['correct'] is None for n in measured)}
        changed = []
        for key, old in numeric_maps['baseline'].items():
            new = numeric_maps['candidate'][key]
            row = {'id': key[0], 'quantity_index': key[1], 'arm': arm,
                   'baseline': old, 'candidate': new}
            transitions.append(row)
            if old['correct'] != new['correct']:
                changed.append({'id': key[0], 'quantity_index': key[1],
                                'baseline': old['correct'], 'candidate': new['correct']})
        output['numeric_transitions'] = changed
        output['former_numeric_pass_controls'] = {
            'n_baseline_pass': sum(n['correct'] is True for n in numeric_maps['baseline'].values()),
            'n_retained': sum(old['correct'] is True and numeric_maps['candidate'][key]['correct'] is True
                              for key, old in numeric_maps['baseline'].items())}
        result['arms'][arm] = output
    save(a.output/'comparison.json', result)
    save(a.output/'numeric_transitions.json', transitions)
    print({arm: {'baseline_numeric': r['baseline']['numeric_correct_required'],
                 'candidate_numeric': r['candidate']['numeric_correct_required'],
                 'required': n_numeric, 'former_pass_controls': r['former_numeric_pass_controls'],
                 'baseline_complete': r['baseline']['audit']['complete_answer_success'],
                 'candidate_complete': r['candidate']['audit']['complete_answer_success']}
           for arm, r in result['arms'].items()})


def main():
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-run', 'baseline-audit', 'candidate-run', 'candidate-audit', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    compare(p.parse_args())


if __name__ == '__main__':
    main()
