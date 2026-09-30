"""Exercise upload -> local OCR/indexing -> local answer with outbound sockets blocked.

Run after setting OFFLINE_MODE, LOCAL_OCR_PYTHON, LOCAL_OCR_MODELS_DIR,
PRIVATE_DATA_DIR and downloading OFFLINE_LLM_MODEL plus EMBED_MODEL in Ollama.
Use a synthetic test PDF; the script deletes its document after the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--question", default="What is this document processed on?")
    parser.add_argument("--expected-fragment", default="computer")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.OFFLINE_MODE:
        raise RuntimeError("Set OFFLINE_MODE=true before running this test")

    from backend.main import app

    pdf_bytes = args.pdf.read_bytes()
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "ocr_provider": settings.PDF_OCR_PROVIDER,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.OLLAMA_LLM_MODEL,
        "embedding_model": settings.EMBED_MODEL,
        "private_data_dir": settings.PRIVATE_DATA_DIR,
    }
    document_id = None
    start = time.perf_counter()
    with TestClient(app) as client:
        health = client.get("/api/health", headers={"Origin": "https://example.org"})
        assert health.json()["privacy_mode"] == "offline"
        assert "access-control-allow-origin" not in health.headers
        result["external_browser_origin_blocked"] = True
        try:
            socket.getaddrinfo("example.org", 443)
        except OSError as exc:
            assert "OFFLINE_MODE blocked" in str(exc)
            result["external_dns_blocked"] = True
        else:
            raise AssertionError("External DNS was available during OFFLINE_MODE")
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=1)
        except OSError as exc:
            assert "OFFLINE_MODE blocked" in str(exc)
            result["external_tcp_blocked"] = True
        else:
            raise AssertionError("External TCP was available during OFFLINE_MODE")
        blocked_scrape = client.post("/api/scrape/url", json={"url": "https://example.org"})
        result["scrape_http_status"] = blocked_scrape.status_code
        assert blocked_scrape.status_code == 403
        blocked_graph = client.get("/api/graphs")
        result["graph_http_status"] = blocked_graph.status_code
        assert blocked_graph.status_code == 403

        try:
            uploaded = client.post("/api/documents/upload", files={
                "file": (args.pdf.name, pdf_bytes, "application/pdf"),
            })
            uploaded.raise_for_status()
            job = uploaded.json()
            document_id = job["id"]
            assert job["queued"] and job["page_count"] == 1
            result["upload_queued_seconds"] = round(time.perf_counter() - start, 2)

            deadline = time.monotonic() + settings.LOCAL_OCR_PAGE_TIMEOUT_SECONDS + 120
            while time.monotonic() < deadline:
                detail_response = client.get(f"/api/documents/{document_id}")
                detail_response.raise_for_status()
                detail = detail_response.json()
                if detail["status"] in {"completed", "partial", "failed"}:
                    break
                time.sleep(2)
            else:
                raise TimeoutError("Offline PDF processing did not finish")
            result["document_status"] = detail["status"]
            result["page_statuses"] = detail["page_statuses"]
            result["processing_seconds"] = round(time.perf_counter() - start, 2)
            assert detail["status"] == "completed", detail.get("error_message")
            assert detail["page_statuses"][0]["status"] == "indexed"

            answered = client.post("/api/query", json={"question": args.question})
            answered.raise_for_status()
            answer = answered.json()
            result["question"] = args.question
            result["answer"] = answer["answer"]
            result["answer_matches_reference"] = args.expected_fragment.lower() in answer["answer"].lower()
            result["answer_method"] = answer["method"]
            result["source_pages"] = [source.get("page") for source in answer.get("sources", [])]
            result["total_seconds"] = round(time.perf_counter() - start, 2)
            assert any(
                source.get("document_id") == document_id and source.get("page") == 1
                for source in answer.get("sources", [])
            ), "Answer has no source link to the uploaded PDF page"
            assert result["answer_matches_reference"], "Local answer did not match the synthetic reference"
        finally:
            if document_id is not None:
                deleted = client.delete(f"/api/documents/{document_id}")
                result["test_document_deleted"] = deleted.status_code == 200

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
