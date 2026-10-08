"""Run a named continuation stage against preserved October 5 inputs."""
import argparse
from pathlib import Path
import subprocess
import sys

from scripts.evaluate_comprehensive import load, save, sha

PREVIOUS = Path(r'C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs\plan_completion_authorized_v1')
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'TestFile/evaluation_completion_2026-10-07'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['development20', 'retry20', 'development50', 'final133'])
    p.add_argument('--tag', default='v1')
    p.add_argument('--preflight', action='store_true')
    p.add_argument('--resume',action='store_true')
    a = p.parse_args()
    if not a.tag.replace('_', '').isalnum(): raise ValueError('Invalid output tag')
    if a.stage == 'final133':
        gate_path = OUTPUT/'FINAL_DISPATCH_GATE.json'
        gate = load(gate_path)
        if not gate.get('approved_from_measured_development_evidence'):
            raise ValueError('Final evaluation gate is not ready')
        inputs = PREVIOUS/'heldout_fact_dedup_v4'
        reference, labels = inputs/'reference_locked.json', inputs/'numeric_labels_locked.json'
        queries, selection = inputs/'query_vectors.npz', inputs/'selection_locked.json'
        corpus = PREVIOUS/'heldout_native_corpus_prepared'
        paths = inputs/'pdf_paths.json'
        size, scope = 133, 'new_issuer_final'
        policies = ['bm25_thai', 'dense', 'simple_rag', 'lexical_first']
    else:
        inputs = OUTPUT/('labels_v11' if a.stage == 'development50' else 'labels_v9')
        reference, labels = inputs/('reference_locked.json' if a.stage == 'development50' else 'reference_v8_locked.json'), inputs/'numeric_labels_locked.json'
        queries = inputs/'query_vectors.npz'
        size = 20 if a.stage == 'development20' else 50
        selection = PREVIOUS/('selection20_locked_v8.json' if size == 20 else 'selection50_locked.json')
        if a.stage == 'retry20':
            selection = OUTPUT/'retry20_infrastructure_selection.json'
            size = len(load(selection))
        corpus = PREVIOUS/'recorded_ocr_corpus_v3'
        paths = PREVIOUS.parent.parent/'work/pdf_paths.json'
        scope, policies = 'development', ['hybrid_current', 'lexical_first']
    output = OUTPUT/(a.stage+'_'+a.tag+('_preflight' if a.preflight else ''))
    args = [sys.executable, '-m', 'scripts.run_capture_paired',
        '--reference', str(reference), '--labels', str(labels), '--pdf-paths', str(paths),
        '--embedding-cache', str(corpus/'embeddings.npz'), '--corpus-json', str(corpus/'corpus.json'),
        '--query-cache', str(queries), '--selection-answers', str(selection), '--expected-pairs', str(size),
        '--budget', str(OUTPUT/'resource_ledger.json'), '--output', str(output),
        '--evaluation-scope', scope, '--ranking-policies', *policies]
    if not a.preflight: args += ['--run']
    if a.resume:args+=['--resume']
    save(OUTPUT/('dispatch_'+a.stage+'_'+a.tag+('_preflight' if a.preflight else '_resume' if a.resume else '')+'.json'), {
        'argv': args, 'source_hashes': {str(x): sha(x) for x in [reference, labels, queries, selection]},
        'predictions_exposed_before_final': (OUTPUT/'FINAL_DRIVER_REPAIR_DISCLOSURE.json').exists() if scope == 'new_issuer_final' else None,
        'human_confirmed': False})
    raise SystemExit(subprocess.call(args, cwd=ROOT))


if __name__ == '__main__': main()
