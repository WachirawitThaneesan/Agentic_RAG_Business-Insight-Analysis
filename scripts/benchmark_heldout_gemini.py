"""Supplemental Gemini answer comparison on frozen, public Thai PDF text.

This is a post-hoc follow-up to the offline held-out benchmark. It reuses its
corpus, local embeddings, BM25 ranking, and answer prompt, but sends answer
generation and agent calls to the configured Vertex Gemini model. It never
performs OCR or sends private PDFs to a cloud service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from sqlalchemy.engine import make_url

from scripts.benchmark_heldout import BM25, _corpus, _embed_texts, _source
from scripts.benchmark_long_document import _create_test_db, _drop_test_db


def _save(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def _run(manifest: dict, chunks: list[dict], vectors, bm25: BM25,
               output: Path, answer_limit: int) -> dict:
    from backend.config import get_settings

    settings = get_settings()
    if settings.OFFLINE_MODE or settings.LLM_PROVIDER != "gemini":
        raise ValueError("Supplemental run requires LLM_PROVIDER=gemini and OFFLINE_MODE=false")
    if not settings.VERTEX_PROJECT or not settings.GOOGLE_APPLICATION_CREDENTIALS:
        raise ValueError("Vertex project and credentials must be configured")

    base_url = settings.DATABASE_URL
    db_name = f"ragdb_step8_gemini_{os.getpid()}"
    await _create_test_db(base_url, db_name)
    url = make_url(base_url).set(database=db_name)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL_SYNC"] = url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    get_settings.cache_clear()

    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.eval.score_layers import score_answers
    from backend.models import Chunk, Document, DocumentPage
    from backend.services.agent import agent_query
    from backend.services.llm import generate, usage

    predictions = {"bm25_gemini": {}, "app_gemini": {}}
    timings = []
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            doc_ids = {}
            for item in manifest["documents"]:
                doc = Document(filename=item["source_file"], doc_type="pdf",
                               status="completed", source_url=item["download_url"])
                db.add(doc)
                await db.flush()
                doc_ids[item["code"]] = doc.id
                db.add_all(DocumentPage(document_id=doc.id, page_number=number,
                                        status="indexed")
                           for number in range(1, item["source_page_count"] + 1))
            for chunk, vector in zip(chunks, vectors):
                db.add(Chunk(document_id=doc_ids[chunk["document"]],
                             chunk_index=chunk["chunk_id"], chunk_text=chunk["text"],
                             embedding=vector.tolist(), summary="",
                             token_count=len(chunk["text"].split()),
                             metadata_={"page": chunk["source_pdf_page"],
                                        "source_kind": "semantic"}))
            await db.commit()

        for index, question in enumerate(manifest["items"][:answer_limit], 1):
            query = question["question_th"]
            hits = [chunks[i] for i in bm25.rank(query, 10)]
            evidence = "\n\n".join(
                f"[{hit['filename']} PDF page {hit['source_pdf_page']}] {hit['text'][:1800]}"
                for hit in hits[:3]
            )
            prompt = (
                "Answer only from the supplied PDF passages. Use the question's language. "
                "Give the exact number, currency, scale, and year when stated. "
                "If evidence is insufficient, say so. Reply with one short answer only.\n\n"
                f"Question: {query}\n\nEvidence:\n{evidence}\n\nAnswer:"
            )
            started = time.perf_counter()
            try:
                baseline_answer = await generate(prompt, temperature=0, max_tokens=180) if hits else "Insufficient evidence."
            except Exception as exc:
                baseline_answer = f"GENERATION_ERROR: {type(exc).__name__}: {exc}"
            baseline_seconds = round(time.perf_counter() - started, 2)
            predictions["bm25_gemini"][question["id"]] = {
                "id": question["id"], "answer": baseline_answer,
                "citations": [_source(hit) for hit in hits[:3]],
            }

            started = time.perf_counter()
            try:
                async with AsyncSessionLocal() as db:
                    result = await agent_query(query, db)
            except Exception as exc:
                result = {"answer": f"AGENT_ERROR: {type(exc).__name__}: {exc}", "sources": []}
            agent_seconds = round(time.perf_counter() - started, 2)
            predictions["app_gemini"][question["id"]] = {
                "id": question["id"], "answer": result["answer"],
                "citations": [{"filename": source.get("filename"),
                               "source_pdf_page": source.get("page")}
                              for source in result.get("sources", [])
                              if source.get("filename") and source.get("page")],
            }
            timings.append({"id": question["id"], "baseline_seconds": baseline_seconds,
                            "agent_seconds": agent_seconds, "usage_after": dict(usage)})
            _save(output / "progress.json", {"completed_questions": index,
                                             "predictions": predictions, "timings": timings})
            print(f"Answered {index}/{answer_limit}: {question['id']}", flush=True)

        documents = {item["code"]: item for item in manifest["documents"]}
        scores = {arm: score_answers(manifest["items"][:answer_limit], documents, rows,
                                     page_space="source")
                  for arm, rows in predictions.items()}
        for arm, rows in predictions.items():
            _save(output / f"{arm}_answers.json", list(rows.values()))
        result = {"purpose": "post-hoc supplemental normal-provider answer comparison",
                  "corpus_mode": "selectable PDF text, no OCR or DuckDB table extraction",
                  "n_documents": len(documents),
                  "n_pages": sum(item["source_page_count"] for item in manifest["documents"]),
                  "n_chunks": len(chunks), "n_answers": answer_limit,
                  "bm25_tokenizer": "pythainlp-newmm", "embedding_model": "bge-m3",
                  "answer_model": settings.GEMINI_MODEL, "answers": scores,
                  "usage": dict(usage), "timings": timings}
        _save(output / "metrics.json", result)
        return result
    finally:
        await engine.dispose()
        await _drop_test_db(base_url, db_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--embedding-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--answer-limit", type=int, default=20)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not 0 < args.answer_limit <= len(manifest["items"]):
        parser.error("answer-limit must be between one and question count")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    chunks = _corpus(manifest, args.corpus_dir)
    vectors = _embed_texts([item["text"] for item in chunks], "bge-m3", args.embedding_cache)
    bm25 = BM25([item["text"] for item in chunks], thai_words=True)
    os.environ["OFFLINE_MODE"] = "false"
    os.environ["LLM_PROVIDER"] = "gemini"
    result = asyncio.run(_run(manifest, chunks, vectors, bm25, output, args.answer_limit))
    print(json.dumps({"answers": result["n_answers"], "usage": result["usage"]}, indent=2))


if __name__ == "__main__":
    main()
