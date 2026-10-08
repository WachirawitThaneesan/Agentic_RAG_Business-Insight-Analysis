"""Publish bounded, lossless evidence archives without altering original runs."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RECOVERY = Path('TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08')
OUTPUT = ROOT/'TestFile/published_2026-10-08'
TEXT_SUFFIXES = {'.json', '.jsonl', '.py', '.md', '.csv', '.txt', '.xml', '.js', '.html'}
ALLOWED_SUFFIXES = TEXT_SUFFIXES | {'.npz', '.png'}
SECRET_PATTERNS = [re.compile(p) for p in (
    rb'AIzaSy[A-Za-z0-9_-]{33}', rb'sk-proj-[A-Za-z0-9_-]{30,}',
    rb'AKIA[A-Z0-9]{16}', rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]


def digest_and_scan(path):
    h = hashlib.sha256()
    previous = b''
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            h.update(chunk)
            if path.suffix in TEXT_SUFFIXES:
                segment = previous+chunk
                if any(p.search(segment) for p in SECRET_PATTERNS):
                    raise ValueError('Potential credential in publication input: '+str(path.relative_to(ROOT)))
                previous = segment[-256:]
    return h.hexdigest()


def publish():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    (OUTPUT/'evidence').mkdir()
    groups = {
        'full498-generation': ['focus498_capture_v3'],
        'full498-final-audit': ['focus498_judge_merged_v5'],
        'full498-initial-audit': ['focus498_judge_v2'],
        'full498-audit-recovery-v3': ['focus498_judge_recovery_v3'],
        'full498-audit-recovery-v4': ['focus498_judge_recovery_v4'],
        'full498-direct-recovery': ['focus498_failed_judge_inputs_v5', 'focus498_direct_judge_recovery_v5'],
        'numeric-experiments': ['candidate_numeric98_v20', 'candidate_numeric98_v21',
            'candidate_numeric98_v21_comparison', 'focus_numeric94_v20', 'focus_numeric94_v21'],
        'source-review-and-checkpoints': ['numeric_reference_blind_review_v1',
            'FULL498_AUDIT_CHECKPOINT_V5.json', 'FINAL22_BINDING_COMPATIBILITY.json',
            'FULL498_GENERATION_CHECKPOINT.json', 'ADVISOR_ACCEPTANCE_498.json'],
        'frozen-corpus': ['fresh32_full_corpus_v1'],
    }
    manifest = {'scope': 'Selected Gemini498 evidence, original file bytes retained in lossless ZIP archives',
        'date_local': '2026-10-08', 'timezone': 'Asia/Bangkok',
        'original_experiments_preserved_locally': True, 'source_pdfs_included': False,
        'runtime_databases_logs_and_temporary_files_included': False,
        'all_local_experiments_archived': False, 'archives': [], 'published_files': []}
    for name, inputs in groups.items():
        files = set()
        for relative in inputs:
            p = ROOT/RECOVERY/relative
            if not p.exists():
                raise FileNotFoundError(p)
            files.update([p] if p.is_file() else (x for x in p.rglob('*') if x.is_file()))
        files = sorted(p for p in files if p.suffix in ALLOWED_SUFFIXES
            and '__pycache__' not in p.parts and not p.name.startswith('.env'))
        archive = OUTPUT/'evidence'/(name+'.zip')
        inventory = []
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for source in files:
                original = source.relative_to(ROOT).as_posix()
                source_sha = digest_and_scan(source)
                z.write(source, original)
                inventory.append({'path': original, 'sha256': source_sha, 'bytes': source.stat().st_size})
        if archive.stat().st_size >= 100*1024**2:
            raise ValueError('Archive exceeds regular GitHub file limit: '+name)
        with zipfile.ZipFile(archive) as z:
            bad = z.testzip()
            if bad:
                raise ValueError('Archive integrity failure: '+bad)
        manifest['archives'].append({'path': archive.relative_to(OUTPUT).as_posix(),
            'sha256': digest_and_scan(archive), 'bytes': archive.stat().st_size, 'files': inventory})
        print(name, len(files), 'files,', round(archive.stat().st_size/1024**2, 2), 'MiB', flush=True)
    source = ROOT/RECOVERY/'focus498_report_final_v3'
    copies = {
        'metrics498.json': source/'metrics498.json',
        'numeric_diagnosis102.json': source/'numeric_diagnosis102.json',
        'per_question498.json': source/'per_question498.json',
        'judge_failures_retained.json': source/'judge_failures_retained.json',
        'results498.png': source/'results498.png',
        'contract_details498.json': ROOT/RECOVERY/'focus498_judge_merged_v5/contract_details.json',
        'resource_ledger_snapshot.json': ROOT/'TestFile/evaluation_completion_2026-10-07/resource_ledger.json',
        'candidate98_comparison.json': ROOT/RECOVERY/'candidate_numeric98_v21_comparison/comparison.json',
        'selection_decision.json': ROOT/RECOVERY/'candidate_numeric98_v21_comparison/SELECTION_DECISION.json',
    }
    for name, source in copies.items():
        source_sha = digest_and_scan(source)
        shutil.copyfile(source, OUTPUT/name)
        if digest_and_scan(OUTPUT/name) != source_sha:
            raise ValueError('Publication copy changed source bytes')
        manifest['published_files'].append({'path': name, 'sha256': source_sha,
            'source': source.relative_to(ROOT).as_posix(), 'bytes': source.stat().st_size})
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print('Publication ready:', len(manifest['archives']), 'verified archives', flush=True)


if __name__ == '__main__':
    publish()
