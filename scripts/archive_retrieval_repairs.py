"""Copy final reports and freeze the complete public-document repair experiment."""
from __future__ import annotations
import argparse, hashlib, json, shutil, zipfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args();root=args.root;repo=args.repo
    docs=repo/'docs/evaluation-repair-2026-10-05'
    raw=repo/'TestFile/evaluation-repair-2026-10-05'
    if docs.exists() or raw.exists():raise ValueError('Version already archived; use a new version')
    docs.mkdir(parents=True);raw.mkdir(parents=True)
    for src in (root/'published_final').iterdir():
        if src.is_file():shutil.copyfile(src,docs/src.name)
    for name in ('reference_locked.json','quarantined.json','alternate_page_decisions.json'):
        shutil.copyfile(root/'labels_v3'/name,raw/name)
    shutil.copyfile(root/'software_tests_final.xml',raw/'software_tests.xml')
    code=root/'frozen_code';code.mkdir(exist_ok=False)
    for folder in ('scripts','backend/eval','backend/services'):
        for src in (repo/folder).rglob('*.py'):
            if '__pycache__' in src.parts:continue
            target=code/src.relative_to(repo);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src,target)
    # Include public page images, raw model decisions, ranked outputs, failed
    # intermediate runs, code snapshots and input hashes. No full PDFs, local
    # embeddings, model weights, environment files or credentials are bundled.
    allowed={'.json','.csv','.md','.png','.py','.xml','.txt'}
    files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in allowed
                 and '__pycache__' not in p.parts)
    ledger={str(p.relative_to(root)).replace('\\','/'):digest(p) for p in files}
    archive=raw/'complete_repair_artifacts.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for src in files:z.write(src,str(src.relative_to(root)).replace('\\','/'))
        z.writestr('SHA256_MANIFEST.json',json.dumps(ledger,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip()
        if bad:raise ValueError('Archive CRC failure '+bad)
        saved=json.loads(z.read('SHA256_MANIFEST.json'))
        for name,expected in saved.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=expected:raise ValueError('Hash mismatch '+name)
    result={'archive_sha256':digest(archive),'file_count':len(files),
        'archive_mib':archive.stat().st_size/1024**2,'crc_verified':True,
        'all_file_hashes_verified':True,'excluded':['full PDFs','embeddings','model weights','credentials'],
        'files':ledger}
    (raw/'artifact_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    report_ledger={p.name:digest(p) for p in docs.iterdir() if p.is_file()}
    (docs/'report_manifest.json').write_text(json.dumps(report_ledger,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__':main()
