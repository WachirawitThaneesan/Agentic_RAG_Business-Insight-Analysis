"""Local Docling OCR adapter with no hosted fallback."""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader

from backend.config import get_settings

settings = get_settings()
_MARKER = "__LOCAL_OCR_RESULT__"


class LocalOCRService:
    def __init__(self) -> None:
        self._worker: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.render_dpi = 300

    def get_pdf_page_count(self, pdf_path: str) -> int:
        return len(PdfReader(pdf_path).pages)

    def _start_worker(self) -> subprocess.Popen:
        python = Path(settings.LOCAL_OCR_PYTHON).expanduser()
        models = Path(settings.LOCAL_OCR_MODELS_DIR).expanduser()
        if not python.is_file() or not models.is_dir():
            raise RuntimeError("Offline Docling Python or model directory is missing")
        repo = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "VERTEX_PROJECT", "TYPHOON_API_KEY",
                    "TYPHOON_OCR_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"):
            env.pop(key, None)
        env.update({
            "PYTHONPATH": str(repo),
            "PYTHONIOENCODING": "utf-8",
            "LOCAL_OCR_MODELS_DIR": str(models),
            "EASYOCR_MODULE_PATH": settings.LOCAL_OCR_EASYOCR_CACHE_DIR or str(models.parent / "easyocr_cache"),
            "HF_HOME": str(models.parent / "hf_cache"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "OMP_NUM_THREADS": "4",
        })
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            [str(python), "-u", "-m", "backend.services.local_ocr_worker"],
            cwd=str(repo), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=creationflags,
        )

    def _request_sync(self, filepath: str, page: int) -> dict[str, Any]:
        with self._lock:
            if self._worker is None or self._worker.poll() is not None:
                self._worker = self._start_worker()
            worker = self._worker
            assert worker.stdin is not None and worker.stdout is not None
            worker.stdin.write(json.dumps({"filepath": filepath, "page": page}) + "\n")
            worker.stdin.flush()
            recent_output = []
            for line in worker.stdout:
                if not line.startswith(_MARKER):
                    recent_output.append(line.strip()[:200])
                    recent_output = recent_output[-5:]
                    continue
                payload = json.loads(line[len(_MARKER):])
                if payload.get("ok"):
                    return payload["result"]
                raise RuntimeError(f"Local OCR failed on PDF page {page}: {payload.get('error')}")
            raise RuntimeError("Local OCR worker exited without a result: " + " | ".join(recent_output))

    def close(self) -> None:
        worker = self._worker
        self._worker = None
        if worker and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)

    async def extract_from_pdf_path(
        self, pdf_path: str, filename: str = "document.pdf",
        pages: list[int] | None = None, render_dpi: int | None = None,
    ) -> dict[str, Any]:
        del filename, render_dpi
        selected = pages or list(range(1, self.get_pdf_page_count(pdf_path) + 1))
        merged = {"raw_pages": [], "pages": [], "text_blocks": [], "tables": [],
                  "raw_tables": [], "table_extraction_warnings": [], "errors": []}
        for page in selected:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._request_sync, str(Path(pdf_path).resolve()), page),
                    timeout=settings.LOCAL_OCR_PAGE_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                self.close()
                raise TimeoutError(f"Local OCR exceeded its page deadline on PDF page {page}") from exc
            for key in merged:
                merged[key].extend(result.get(key, []))
        return merged

    async def extract_from_pdf(
        self, pdf_bytes: bytes, filename: str = "document.pdf", pages: list[int] | None = None,
    ) -> dict[str, Any]:
        temp_dir = Path(settings.PRIVATE_DATA_DIR) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pdf", delete=False) as temp:
            temp.write(pdf_bytes)
            path = Path(temp.name)
        try:
            return await self.extract_from_pdf_path(str(path), filename, pages)
        finally:
            path.unlink(missing_ok=True)

    async def extract_from_image(
        self, image_bytes: bytes, mime_type: str = "image/png",
        filename: str = "image.png", page_number: int = 1,
    ) -> dict[str, Any]:
        del mime_type
        with Image.open(io.BytesIO(image_bytes)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PDF")
        result = await self.extract_from_pdf(buffer.getvalue(), filename, pages=[1])
        for key in ("raw_pages", "pages", "tables", "raw_tables"):
            for item in result[key]:
                item["page"] = page_number
        return result


ocr_service = LocalOCRService()
