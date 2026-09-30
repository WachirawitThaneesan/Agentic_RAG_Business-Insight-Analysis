"""The API-owned PDF queue must not schedule duplicate work."""

import asyncio

from backend.services import document_jobs


def test_same_document_is_not_queued_twice(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        async def fake_job(_document_id):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(document_jobs, "_run_pdf_job", fake_job)
        assert document_jobs.enqueue_pdf_job(12345) is True
        assert document_jobs.is_pdf_job_active(12345) is True
        assert document_jobs.enqueue_pdf_job(12345) is False
        await started.wait()
        await document_jobs.cancel_pdf_job(12345)
        await asyncio.sleep(0)
        assert 12345 not in document_jobs._jobs
        assert document_jobs.is_pdf_job_active(12345) is False

    asyncio.run(scenario())


def test_saved_path_is_unique_to_document_id():
    assert document_jobs.saved_upload_path(10, "PDF").name == "10.pdf"
    assert document_jobs.saved_upload_path(11, "pdf") != document_jobs.saved_upload_path(10, "pdf")
