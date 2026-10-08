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
import hashlib
import numpy as np
from pathlib import Path

from sqlalchemy.engine import make_url

from scripts.benchmark_heldout import BM25, _corpus, _embed_texts, _source
from scripts.benchmark_long_document import _create_test_db, _drop_test_db


def _save(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def _run(manifest: dict, chunks: list[dict], vectors, bm25: BM25,
               output: Path, answer_limit: int, meter=None, query_vectors=None) -> dict:
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
    retrieval = []
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
            if meter:
                meter.phase.update(id=question['id'], arm='retrieval')
            if query_vectors is not None:
                from backend.services.rag import vector_search
                qv = query_vectors[index-1]
                similarity = vectors @ qv / np.maximum(np.linalg.norm(vectors,axis=1)*np.linalg.norm(qv),1e-12)
                dense = [chunks[int(i)] for i in np.argsort(-similarity,kind='stable')[:5]]
                async with AsyncSessionLocal() as db:
                    app_hits = await vector_search(query,db,top_k=5)
                arms = {'bm25': [_source(h) for h in hits[:5]], 'dense': [_source(h) for h in dense],
                        'app_hybrid': [{'filename': h['filename'], 'source_pdf_page': h.get('page')} for h in app_hits]}
                doc = next(d for d in manifest['documents'] if d['code']==question['document'])
                target = (doc['source_file'],question['source_pdf_page'])
                retrieval.append({'id':question['id'],'target':target,'arms':arms,
                    'page_hit_at_5':{arm:any((h['filename'],h['source_pdf_page'])==target for h in rows[:5]) for arm,rows in arms.items()}})
                _save(output/'retrieval.json',retrieval)
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
            if meter:
                meter.phase.update(id=question['id'], arm='bm25_gemini')
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
            if meter:
                meter.phase.update(id=question['id'], arm='app_gemini')
            try:
                async with AsyncSessionLocal() as db:
                    result = await agent_query(query, db)
            except Exception as exc:
                result = {"answer": f"AGENT_ERROR: {type(exc).__name__}: {exc}", "sources": []}
            agent_seconds = round(time.perf_counter() - started, 2)
            predictions["app_gemini"][question["id"]] = {
                "id": question["id"], "answer": result["answer"],
                "full_result": result,
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
        scored_items = [item for item in manifest["items"][:answer_limit] if item.get('answerable', True)]
        scores = {arm: score_answers(scored_items, documents, rows,
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
        for arm, score in scores.items():
            score['n_strict_supported_correct'] = sum(d['fact_status']=='correct' and d['all_required_pages_cited'] for d in score['details'])
        result['retrieval_page_hit_at_5'] = {arm: sum(r['page_hit_at_5'][arm] for r in retrieval) for arm in ('bm25','dense','app_hybrid')}
        result['label_review'] = manifest.get('label_review')
        result['limitations'] = manifest.get('limitations', [])
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
    parser.add_argument("--measure", action='store_true', help='Record calls/resources and BM25/dense/app page Hit@5')
    parser.add_argument("--capture-context", action='store_true', help='Save exact public-document generation prompts for claim evaluation; requires --measure')
    args = parser.parse_args()
    if args.capture_context and not args.measure:
        parser.error('--capture-context requires --measure')
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not 0 < args.answer_limit <= len(manifest["items"]):
        parser.error("answer-limit must be between one and question count")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["OFFLINE_MODE"] = "false"
    os.environ["LLM_PROVIDER"] = "gemini"
    # Native-text experiment must not see production financial cells.
    os.environ['DUCKDB_PATH'] = str(output/'isolated_warehouse.duckdb')
    from backend.config import get_settings
    get_settings.cache_clear()
    from scripts.experiment_meter import ExperimentMeter
    meter = ExperimentMeter(output, capture_context=args.capture_context) if args.measure else None
    if meter: meter.start()
    try:
        _save(output/'reference_locked.json',manifest)
        repo = Path(__file__).resolve().parents[1]
        files = list((repo/'backend').rglob('*.py')) + list((repo/'scripts').glob('*.py'))
        _save(output/'code_hashes.json',{str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
        chunks = _corpus(manifest, args.corpus_dir)
        args.embedding_cache.parent.mkdir(parents=True,exist_ok=True)
        vectors = _embed_texts([item["text"] for item in chunks], "bge-m3", args.embedding_cache)
        query_vectors = _embed_texts([q['question_th'] for q in manifest['items'][:args.answer_limit]], 'bge-m3', output/'query_vectors.npz') if args.measure else None
        bm25 = BM25([item["text"] for item in chunks], thai_words=True)
        result = asyncio.run(_run(manifest, chunks, vectors, bm25, output, args.answer_limit, meter, query_vectors))
    finally:
        if meter: meter.finish()
    print(json.dumps({"answers": result["n_answers"], "usage": result["usage"]}, indent=2))


if __name__ == "__main__":
    main()
