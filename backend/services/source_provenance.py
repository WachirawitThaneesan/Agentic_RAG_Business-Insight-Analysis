"""Hash the saved upload itself; never substitute a reference/PDF label hash."""
import hashlib
from pathlib import Path


def saved_source_hash(path):
    source=Path(path)
    if not source.is_file():return None
    digest=hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def bind_saved_source(document,path):
    actual=saved_source_hash(path)
    expected=getattr(document,'source_sha256',None)
    if expected and actual!=expected:raise ValueError('Saved upload differs from its stored source hash')
    document.source_sha256=actual
    return actual
