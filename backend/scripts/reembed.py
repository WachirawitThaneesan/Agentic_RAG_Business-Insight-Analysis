"""Re-embed all chunks with the currently-configured EMBED_MODEL.

Used when switching embedding models (e.g. nomic-embed-text 768d -> bge-m3 1024d).
Prereqs: the `chunks.embedding` column must already be the right dimension and
EMBED_MODEL in .env must point at the new model. Idempotent: re-run to fill any
rows still NULL (pass --all to redo every row).

    python -m backend.scripts.reembed          # only rows with NULL embedding
    python -m backend.scripts.reembed --all     # re-embed everything
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx
import psycopg2

from backend.config import get_settings

s = get_settings()


# bge-m3 caps at ~8192 tokens; very long OCR-page chunks overflow it and 500.
# Truncate to a safe char budget (Thai can be >1 token/char) before embedding.
_MAX_CHARS = 3500


def embed(text: str) -> list[float]:
    text = text or ""
    # Token-heavy chunks (HTML tables) can overflow even at _MAX_CHARS, so back
    # off progressively on 500 rather than dropping the chunk entirely.
    last_exc = None
    for cap in (_MAX_CHARS, 2000, 1000, 500):
        try:
            r = httpx.post(
                f"{s.OLLAMA_HOST}/api/embeddings",
                json={"model": s.EMBED_MODEL, "prompt": text[:cap]},
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["embedding"]
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            continue
    raise last_exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-embed every row (not just NULLs)")
    args = ap.parse_args()

    con = psycopg2.connect(s.DATABASE_URL_SYNC)
    con.autocommit = False
    cur = con.cursor()

    where = "" if args.all else "WHERE embedding IS NULL"
    cur.execute(f"SELECT id, chunk_text FROM chunks {where} ORDER BY id")
    rows = cur.fetchall()
    total = len(rows)
    print(f"model={s.EMBED_MODEL} | rows to embed: {total}", flush=True)

    done = 0
    t0 = time.time()
    for cid, text in rows:
        try:
            vec = embed(text or "")
        except Exception as exc:
            print(f"  id={cid} embed failed: {exc}", flush=True)
            continue
        cur.execute("UPDATE chunks SET embedding = %s WHERE id = %s", (str(vec), cid))
        done += 1
        if done % 100 == 0:
            con.commit()
            rate = done / (time.time() - t0)
            eta = (total - done) / rate if rate else 0
            print(f"  {done}/{total}  ({rate:.1f}/s, ETA {eta/60:.0f} min)", flush=True)
    con.commit()

    cur.execute("SELECT COUNT(*), COUNT(embedding) FROM chunks")
    print(f"done in {(time.time()-t0)/60:.1f} min | chunks/with-embedding: {cur.fetchone()}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
