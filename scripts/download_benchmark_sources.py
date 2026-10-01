"""Download public benchmark PDFs and verify their frozen SHA-256 hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.output.resolve()
    for doc in manifest['documents']:
        path = (root/doc['source_file']).resolve()
        if path.parent != root:
            raise ValueError('Source filename must be a single filename')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != doc['source_sha256']:
                raise ValueError(f'Existing file hash differs: {path.name}')
            print('Verified existing',path.name); continue
        partial = path.with_suffix(path.suffix+'.part')
        with requests.get(doc['download_url'],stream=True,timeout=(15,180)) as response:
            response.raise_for_status()
            with partial.open('xb') as target:
                for block in response.iter_content(1024*1024):
                    target.write(block)
        payload = partial.read_bytes()
        if not payload.startswith(b'%PDF-') or hashlib.sha256(payload).hexdigest()!=doc['source_sha256']:
            raise ValueError(f'Download content/hash differs; retained {partial.name}')
        partial.rename(path)
        print('Downloaded and verified',path.name)


if __name__ == '__main__':
    main()
