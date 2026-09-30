"""Download the frozen public held-out PDFs and verify their SHA-256 hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx
import pymupdf


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("TestFile/heldout_reference_v1.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for item in manifest["documents"]:
        target = output / item["source_file"]
        expected = item["source_sha256"]
        if target.is_file() and _hash(target) == expected:
            print(f"Verified existing {target.name}")
            continue
        if target.exists():
            raise ValueError(f"Existing file has a different SHA-256: {target}")
        temp = target.with_suffix(".part")
        digest = hashlib.sha256()
        count = 0
        try:
            with httpx.Client(timeout=60, trust_env=False) as client:
                with client.stream("GET", item["download_url"], follow_redirects=False) as response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise RuntimeError(f"Unexpected HTTP {response.status_code}")
                    with temp.open("wb") as stream:
                        for block in response.iter_bytes():
                            count += len(block)
                            if count > 100_000_000:
                                raise ValueError("PDF exceeds 100 MB benchmark limit")
                            digest.update(block)
                            stream.write(block)
            if digest.hexdigest() != expected:
                raise ValueError(f"Downloaded SHA-256 differs for {target.name}")
            with pymupdf.open(temp) as pdf:
                if len(pdf) != item["source_page_count"]:
                    raise ValueError(f"Downloaded page count differs for {target.name}")
            temp.replace(target)
            print(f"Downloaded and verified {target.name}: {count} bytes")
        finally:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
