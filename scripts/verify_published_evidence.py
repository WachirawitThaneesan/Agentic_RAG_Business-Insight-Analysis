"""Verify compressed evidence against the original-byte publication manifest."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def sha_stream(stream):
    h = hashlib.sha256()
    while chunk := stream.read(1024*1024):
        h.update(chunk)
    return h.hexdigest()


def verify(directory):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    count = 0
    for record in manifest['archives']:
        archive = directory/record['path']
        with archive.open('rb') as stream:
            if sha_stream(stream) != record['sha256'] or archive.stat().st_size != record['bytes']:
                raise ValueError('Published archive changed: '+record['path'])
        with zipfile.ZipFile(archive) as z:
            expected = {f['path']: f for f in record['files']}
            if set(z.namelist()) != set(expected) or len(z.namelist()) != len(expected):
                raise ValueError('Archive member inventory differs')
            for path, item in expected.items():
                parts = PurePosixPath(path)
                if parts.is_absolute() or '..' in parts.parts or ':' in path:
                    raise ValueError('Unsafe archive path')
                with z.open(path) as stream:
                    if sha_stream(stream) != item['sha256'] or z.getinfo(path).file_size != item['bytes']:
                        raise ValueError('Archived original bytes changed: '+path)
                count += 1
        print('Verified', record['path'], flush=True)
    for record in manifest['published_files']:
        file = directory/record['path']
        with file.open('rb') as stream:
            if sha_stream(stream) != record['sha256'] or file.stat().st_size != record['bytes']:
                raise ValueError('Published result copy changed: '+record['path'])
    print(f'Verified {len(manifest["archives"])} archives, {count} original files, and {len(manifest["published_files"])} readable copies.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1]/'TestFile/published_2026-10-08')
    verify(p.parse_args().directory)
