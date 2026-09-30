"""Compare BM25, dense retrieval, and the app's hybrid/offline agent on held-out PDFs.

The PDFs are indexed from their selectable text. This isolates retrieval and
answering from OCR; it is not an end-to-end OCR accuracy experiment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
import pymupdf
from sqlalchemy.engine import make_url

from scripts.benchmark_long_document import _create_test_db, _drop_test_db


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _windows(text: str, limit: int = 1800, overlap: int = 180) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    result = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundary = text.rfind(" ", max(start, end - 180), end)
            if boundary > start:
                end = boundary
        result.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [value for value in result if value]


def _corpus(manifest: dict, corpus_dir: Path) -> list[dict]:
    chunks = []
    for item in manifest["documents"]:
        path = corpus_dir / item["source_file"]
        if not path.is_file() or _sha256(path) != item["source_sha256"]:
            raise ValueError(f"Missing PDF or SHA-256 mismatch: {path}")
        with pymupdf.open(path) as pdf:
            if len(pdf) != item["source_page_count"]:
                raise ValueError(f"Page-count mismatch: {path}")
            for page_index, page in enumerate(pdf):
                for part, text in enumerate(_windows(page.get_text())):
                    chunks.append({"chunk_id": len(chunks), "document": item["code"],
                                   "filename": item["source_file"],
                                   "source_pdf_page": page_index + 1,
                                   "part": part, "text": text})
    return chunks


def _embed_texts(texts: list[str], model: str, cache: Path) -> np.ndarray:
    fingerprint = hashlib.sha256(
        (model + "\n" + "\n".join(texts)).encode("utf-8")
    ).hexdigest()
    if cache.is_file():
        with np.load(cache) as saved:
            vectors = saved["vectors"]
            cached_fingerprint = str(saved["fingerprint"]) if "fingerprint" in saved.files else None
        if vectors.shape[0] == len(texts):
            if cached_fingerprint == fingerprint:
                return vectors
            if cached_fingerprint is None:
                # Upgrade the cache written by the initial Step 8 pilot.
                np.savez_compressed(cache, vectors=vectors, fingerprint=fingerprint)
                return vectors
    vectors = []
    with httpx.Client(timeout=300, trust_env=False) as client:
        for start in range(0, len(texts), 12):
            batch = texts[start:start + 12]
            response = client.post("http://127.0.0.1:11434/api/embed",
                                   json={"model": model, "input": batch,
                                         "keep_alive": "30m"})
            response.raise_for_status()
            returned = response.json()["embeddings"]
            if len(returned) != len(batch):
                raise RuntimeError("Ollama returned a partial embedding batch")
            vectors.extend(returned)
            print(f"Embedded {len(vectors)}/{len(texts)}", flush=True)
    array = np.asarray(vectors, dtype=np.float32)
    if array.shape[1] != 1024:
        raise ValueError(f"Expected pgvector 1024 dimensions, got {array.shape[1]}")
    np.savez_compressed(cache, vectors=array, fingerprint=fingerprint)
    return array


def _tokens(value: str, *, thai_words: bool = False) -> list[str]:
    if thai_words:
        from pythainlp.tokenize import word_tokenize

        return [token.casefold() for token in word_tokenize(value, engine="newmm")
                if re.fullmatch(r"[a-zA-Z]+|\d+(?:\.\d+)?|[ก-๙]+", token)]
    return re.findall(r"[a-zA-Z]+|\d+(?:\.\d+)?|[ก-๙]+", value.lower())


class BM25:
    def __init__(self, texts: list[str], *, thai_words: bool = False) -> None:
        self.thai_words = thai_words
        self.rows = [Counter(_tokens(text, thai_words=thai_words)) for text in texts]
        self.lengths = np.asarray([sum(row.values()) for row in self.rows], dtype=np.float32)
        self.average = float(self.lengths.mean()) if len(self.lengths) else 1.0
        self.df = Counter(word for row in self.rows for word in row)
        self.n = len(self.rows)

    def rank(self, query: str, limit: int) -> list[int]:
        terms = set(_tokens(query, thai_words=self.thai_words))
        scores = np.zeros(self.n, dtype=np.float32)
        for term in terms:
            df = self.df.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for index, row in enumerate(self.rows):
                tf = row.get(term, 0)
                if tf:
                    scores[index] += idf * tf * 2.5 / (
                        tf + 1.5 * (0.25 + 0.75 * self.lengths[index] / self.average)
                    )
        ranked = np.argsort(-scores, kind="stable")
        return [int(index) for index in ranked if scores[index] > 0][:limit]


def _source(hit: dict) -> dict:
    return {"document": hit["document"], "filename": hit["filename"],
            "source_pdf_page": hit["source_pdf_page"]}


async def _run_db(manifest: dict, chunks: list[dict], embeddings: np.ndarray,
                  bm25: BM25, output: Path, answer_limit: int, db_name: str) -> dict:
    from backend.config import get_settings

    base_url = get_settings().DATABASE_URL
    await _create_test_db(base_url, db_name)
    url = make_url(base_url).set(database=db_name)
    os.environ.update({
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "DATABASE_URL_SYNC": url.set(drivername="postgresql").render_as_string(hide_password=False),
        "OFFLINE_MODE": "true", "OFFLINE_LLM_MODEL": "gemma3:4b",
        "EMBED_MODEL": "bge-m3", "GRAPH_BUILD_ENABLED": "false",
        "PRIVATE_DATA_DIR": str(output / "private"),
    })
    get_settings.cache_clear()

    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.eval.score_layers import score_answers, score_search
    from backend.models import Chunk, Document, DocumentPage
    from backend.services.agent import agent_query
    from backend.services.llm import generate
    from backend.services.rag import vector_search

    doc_ids = {}
    rows = {item["code"]: item for item in manifest["documents"]}
    details = []
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            for item in manifest["documents"]:
                doc = Document(filename=item["source_file"], doc_type="pdf",
                               status="completed", source_url=item["download_url"])
                db.add(doc)
                await db.flush()
                doc_ids[item["code"]] = doc.id
                db.add_all(DocumentPage(document_id=doc.id, page_number=number,
                                        status="indexed")
                           for number in range(1, item["source_page_count"] + 1))
            for chunk, vector in zip(chunks, embeddings):
                db.add(Chunk(document_id=doc_ids[chunk["document"]],
                             chunk_index=chunk["chunk_id"], chunk_text=chunk["text"],
                             embedding=vector.tolist(), summary="", token_count=len(chunk["text"].split()),
                             metadata_={"page": chunk["source_pdf_page"],
                                        "source_kind": "semantic"}))
            await db.commit()

        prediction_sets = {name: {} for name in ("bm25", "dense", "app_hybrid")}
        answer_sets = {name: {} for name in ("bm25_rag", "app_agent")}
        for index, question in enumerate(manifest["items"]):
            query = question["question_th"]
            start = time.perf_counter()
            lexical = bm25.rank(query, 10)
            bm_hits = [chunks[i] for i in lexical]
            async with AsyncSessionLocal() as db:
                app_hits = await vector_search(query, db, top_k=10)
            dense_query = await _embed_query(query)
            norm = embeddings / np.maximum(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-9)
            query_norm = dense_query / max(float(np.linalg.norm(dense_query)), 1e-9)
            dense_ids = np.argsort(-(norm @ query_norm), kind="stable")[:10]
            dense_hits = [chunks[int(i)] for i in dense_ids]
            prediction_sets["bm25"][question["id"]] = {"id": question["id"],
                                                        "results": [_source(h) for h in bm_hits]}
            prediction_sets["dense"][question["id"]] = {"id": question["id"],
                                                        "results": [_source(h) for h in dense_hits]}
            prediction_sets["app_hybrid"][question["id"]] = {"id": question["id"],
                                                             "results": [{"filename": h["filename"],
                                                                          "source_pdf_page": h["page"]}
                                                                         for h in app_hits]}
            entry = {"id": question["id"], "retrieval_seconds": round(time.perf_counter() - start, 2),
                     "app_methods": [h.get("retrieval_method") for h in app_hits[:5]]}

            if index < answer_limit:
                evidence = "\n\n".join(
                    f"[{h['filename']} PDF page {h['source_pdf_page']}] {h['text'][:1800]}"
                    for h in bm_hits[:3]
                )
                prompt = (
                    "Answer only from the supplied PDF passages. Use the question's language. "
                    "Give the exact number, currency, scale, and year when stated. "
                    "If evidence is insufficient, say so. Reply with one short answer only.\n\n"
                    f"Question: {query}\n\nEvidence:\n{evidence}\n\nAnswer:"
                )
                answer_start = time.perf_counter()
                if bm_hits:
                    try:
                        baseline_answer = await generate(prompt, temperature=0, max_tokens=180)
                    except Exception as exc:
                        baseline_answer = f"GENERATION_ERROR: {type(exc).__name__}"
                else:
                    baseline_answer = "Insufficient evidence."
                answer_sets["bm25_rag"][question["id"]] = {
                    "id": question["id"], "answer": baseline_answer,
                    "citations": [_source(hit) for hit in bm_hits[:3]],
                }
                entry["bm25_answer_seconds"] = round(time.perf_counter() - answer_start, 2)

                answer_start = time.perf_counter()
                try:
                    async with AsyncSessionLocal() as db:
                        app = await agent_query(query, db)
                except Exception as exc:
                    app = {"answer": f"AGENT_ERROR: {type(exc).__name__}: {exc}", "sources": []}
                answer_sets["app_agent"][question["id"]] = {
                    "id": question["id"], "answer": app["answer"],
                    "citations": [{"filename": source.get("filename"),
                                   "source_pdf_page": source.get("page")}
                                  for source in app.get("sources", [])
                                  if source.get("filename") and source.get("page")],
                }
                entry["agent_answer_seconds"] = round(time.perf_counter() - answer_start, 2)
                print(f"Answered {index + 1}/{answer_limit}: {question['id']}", flush=True)
            details.append(entry)
            (output / "progress.json").write_text(
                json.dumps({"completed_questions": index + 1,
                            "answer_sets": answer_sets, "timings": details},
                           ensure_ascii=False, indent=2), encoding="utf-8")

        documents = {item["code"]: item for item in manifest["documents"]}
        retrieval_scores = {name: score_search(manifest["items"], documents, predictions, k=5,
                                               page_space="source")
                            for name, predictions in prediction_sets.items()}
        answered_items = manifest["items"][:answer_limit]
        answer_scores = {name: score_answers(answered_items, documents, predictions,
                                            page_space="source")
                         for name, predictions in answer_sets.items()} if answer_limit else {}
        for name, predictions in prediction_sets.items():
            (output / f"{name}_predictions.json").write_text(
                json.dumps(list(predictions.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        for name, predictions in answer_sets.items():
            if answer_limit:
                (output / f"{name}_answers.json").write_text(
                    json.dumps(list(predictions.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        result = {"n_documents": len(rows), "n_pages": sum(d["source_page_count"] for d in rows.values()),
                  "n_chunks": len(chunks), "n_questions": len(manifest["items"]),
                  "n_answers": answer_limit, "corpus_mode": "selectable PDF text, no OCR",
                  "bm25_tokenizer": "pythainlp-newmm" if bm25.thai_words else "regex",
                  "embedding_model": "bge-m3", "answer_model": "gemma3:4b",
                  "retrieval": retrieval_scores, "answers": answer_scores, "timings": details}
        (output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        return result
    finally:
        await engine.dispose()
        await _drop_test_db(base_url, db_name)


async def _embed_query(text: str) -> np.ndarray:
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post("http://127.0.0.1:11434/api/embed",
                                     json={"model": "bge-m3", "input": text})
        response.raise_for_status()
        return np.asarray(response.json()["embeddings"][0], dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("TestFile/heldout_reference_v1.json"))
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--answer-limit", type=int, default=0)
    parser.add_argument("--thai-bm25", action="store_true",
                        help="Use PyThaiNLP newmm word segmentation for the BM25 baseline")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not 0 <= args.answer_limit <= len(manifest["items"]):
        raise ValueError("answer-limit must be between zero and question count")
    chunks = _corpus(manifest, args.corpus_dir)
    (output / "corpus_manifest.json").write_text(
        json.dumps({"documents": manifest["documents"], "chunks": len(chunks),
                    "chunk_chars": 1800, "overlap_chars": 180}, indent=2), encoding="utf-8")
    texts = [chunk["text"] for chunk in chunks]
    embeddings = _embed_texts(texts, "bge-m3", output / "embeddings.npz")
    bm25 = BM25(texts, thai_words=args.thai_bm25)
    name = f"ragdb_step8_heldout_{os.getpid()}"
    result = asyncio.run(_run_db(manifest, chunks, embeddings, bm25, output,
                                 args.answer_limit, name))
    print(json.dumps({"pages": result["n_pages"], "chunks": result["n_chunks"],
                      "search": {key: round(value["hit_at_k"], 3)
                                 for key, value in result["retrieval"].items()}}, indent=2))


if __name__ == "__main__":
    main()
