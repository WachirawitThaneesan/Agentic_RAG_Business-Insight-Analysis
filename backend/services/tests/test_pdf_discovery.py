"""Exercise discovery boundaries and provenance without contacting public sites."""

import asyncio

import httpx

from backend.services.pdf_discovery import CrawlLimits, PublicPdfCrawler, download_public_pdfs


PUBLIC_IP = lambda _host: ["93.184.215.14"]
PDF = b"%PDF-1.4\n" + b"report content\n" * 100
LIMITS = CrawlLimits(max_pages=4, max_depth=2, max_sitemaps=2,
                     max_pdfs=4, max_seconds=10, request_delay=0)


def _client(routes, seen):
    def handle(request):
        seen.append(str(request.url))
        status, content_type, body = routes.get(request.url.path, (404, "text/plain", b"missing"))
        return httpx.Response(status, headers={"content-type": content_type}, content=body)

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_follows_report_page_and_sitemap_and_probes_download_url():
    seen = []
    routes = {
        "/robots.txt": (200, "text/plain", b"User-agent: *\nAllow: /\nSitemap: https://reports.example.test/map.xml"),
        "/start": (200, "text/html", b'<a href="/reports/2024">Annual report 2024</a>'),
        "/reports/2024": (200, "text/html", b'<a href="/download?id=1">Download report PDF</a>'),
        "/download": (200, "application/octet-stream", PDF),
        "/map.xml": (200, "application/xml", b'<urlset><url><loc>https://reports.example.test/files/sustainability.pdf</loc></url></urlset>'),
        "/files/sustainability.pdf": (200, "application/pdf", PDF),
    }
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/start", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert {item["url"] for item in result["pdfs"]} == {
        "https://reports.example.test/download?id=1",
        "https://reports.example.test/files/sustainability.pdf",
    }
    assert any(item["discovery_page"].endswith("/reports/2024") for item in result["pdfs"])
    assert result["browser_fallback_used"] is False
    assert "https://reports.example.test/map.xml" in result["sitemaps_checked"]


def test_robots_disallow_is_recorded_without_fetching_pdf():
    seen = []
    routes = {
        "/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /private/"),
        "/start": (200, "text/html", b'<a href="/private/report.pdf">Report PDF</a>'),
    }
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/start", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert result["pdfs"] == []
    assert any(item["reason"] == "robots_disallow" for item in result["blocked"])
    assert all("/private/report.pdf" not in url for url in seen)


def test_robots_http_403_is_unavailable_and_page_can_still_be_checked():
    seen = []
    routes = {
        "/robots.txt": (403, "text/plain", b""),
        "/start": (200, "text/html", b'<a href="/report.pdf">Annual report PDF</a>'),
        "/report.pdf": (200, "application/pdf", PDF),
    }
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/start", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert result["pdfs"][0]["url"].endswith("/report.pdf")
    assert any(item["stage"] == "robots" for item in result["failures"])


def test_browser_is_used_only_after_plain_html_and_sitemap_find_nothing():
    seen = []
    routes = {
        "/robots.txt": (404, "text/plain", b""),
        "/start": (200, "text/html", b"<html><script>renderLinks()</script></html>"),
        "/report.pdf": (200, "application/pdf", PDF),
    }
    calls = []
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/start", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover(
            lambda url: calls.append(url) or [{"url": "/report.pdf", "text": "Annual PDF"}],
        )
    assert calls == ["https://reports.example.test/start"]
    assert result["browser_fallback_used"]
    assert result["pdfs"][0]["url"].endswith("/report.pdf")


def test_viewer_iframe_and_static_script_pdf_are_verified():
    seen = []
    routes = {
        "/robots.txt": (404, "text/plain", b""),
        "/start": (200, "text/html", b'<a href="/report/viewer">Annual report</a>'),
        "/report/viewer": (200, "text/html", b'''
            <iframe src="https://cdn.example.test/th/report_2567.pdf#page=1"></iframe>
            <script>const pdf = "https://cdn.example.test/th/financial_2567.pdf#page=2";</script>
        '''),
        "/th/report_2567.pdf": (200, "application/pdf", PDF),
        "/th/financial_2567.pdf": (200, "application/pdf", PDF),
    }
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/start", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert {item["url"] for item in result["pdfs"]} == {
        "https://cdn.example.test/th/report_2567.pdf",
        "https://cdn.example.test/th/financial_2567.pdf",
    }
    assert all(item["discovery_page"].endswith("/report/viewer") for item in result["pdfs"])


def test_pdf_named_html_viewer_resolves_embedded_storage_pdf():
    seen = []
    routes = {
        "/robots.txt": (404, "text/plain", b""),
        "/th/reports": (200, "text/html", b'<a href="/th/documents/annual-2024-th.pdf">Annual report 2024 TH</a>'),
        "/th/documents/annual-2024-th.pdf": (200, "text/html", b'<html><pdf-viewer src="/storage/annual-2024-th.pdf"></pdf-viewer></html>'),
        "/storage/annual-2024-th.pdf": (206, "application/pdf", PDF),
    }
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/th/reports", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert len(result["pdfs"]) == 1
    assert result["pdfs"][0]["url"].endswith("/storage/annual-2024-th.pdf")
    assert result["pdfs"][0]["via_viewer"].endswith("/th/documents/annual-2024-th.pdf")
    assert result["pdfs"][0]["discovery_page"].endswith("/th/reports")


def test_script_built_flipbook_resolves_thai_pdf():
    seen = []
    routes = {
        "/robots.txt": (404, "text/plain", b""),
        "/th/reports": (200, "text/html", b'<a href="/th/document/viewer/report-2024">Annual report 2024</a>'),
        "/th/document/viewer/report-2024": (200, "text/html", b'''
            <script>let url = `https://hub.example.test/th/documents/154891/flipbook#page=${page}`;</script>
        '''),
        "/th/documents/154891/flipbook": (200, "text/html", b'''
            <html><flipbook src="https://hub.example.test/storage/annual-2024-th.pdf"></flipbook></html>
        '''),
        "/storage/annual-2024-th.pdf": (200, "application/pdf", PDF),
    }
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/th/reports", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert len(result["pdfs"]) == 1
    assert result["pdfs"][0]["url"].endswith("/storage/annual-2024-th.pdf")
    assert result["pdfs"][0]["discovery_page"].endswith("/th/document/viewer/report-2024")


def test_thai_annual_report_wins_small_pdf_budget_with_empty_download_label():
    seen = []
    routes = {
        "/robots.txt": (404, "text/plain", b""),
        "/th/start": (200, "text/html", b'''
            <a href="/files/factsheet.pdf">Factsheet</a>
            <table><tr><td><a href="/files/one-report-2024-th.pdf"></a></td>
            <td>Annual report 2024</td></tr></table>
        '''),
        "/files/factsheet.pdf": (200, "application/pdf", PDF),
        "/files/one-report-2024-th.pdf": (200, "application/pdf", PDF),
    }
    limits = CrawlLimits(max_pages=1, max_depth=0, max_sitemaps=0,
                         max_pdfs=1, max_seconds=10, request_delay=0)
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/th/start", limits,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert result["pdfs"][0]["url"].endswith("/one-report-2024-th.pdf")
    assert "Annual report 2024" in result["pdfs"][0]["anchor_text"]


def test_recent_thai_report_wins_archive_pdf_budget():
    seen = []
    routes = {
        "/robots.txt": (404, "text/plain", b""),
        "/th/start": (200, "text/html", b'''
            <a href="/annual-reports/2016/old-ar2016-th.pdf">Annual report 2016</a>
            <a href="/annual-reports/2024/new-ar2024-th.pdf">Annual report 2024</a>
        '''),
        "/annual-reports/2016/old-ar2016-th.pdf": (200, "application/pdf", PDF),
        "/annual-reports/2024/new-ar2024-th.pdf": (200, "application/pdf", PDF),
    }
    limits = CrawlLimits(max_pages=1, max_depth=0, max_sitemaps=0,
                         max_pdfs=1, max_seconds=10, request_delay=0)
    with _client(routes, seen) as client:
        result = PublicPdfCrawler("https://reports.example.test/th/start", limits,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert result["pdfs"][0]["url"].endswith("/new-ar2024-th.pdf")


def test_download_hash_deduplicates_and_saves_source_manifest(tmp_path):
    seen = []
    routes = {
        "/one": (200, "application/pdf", PDF),
        "/two": (200, "application/pdf", PDF),
    }
    discovery = {"seed_url": "https://reports.example.test/start", "checked_at": "2026-09-27",
                 "pdfs": [{"url": f"https://reports.example.test/{name}",
                           "discovery_page": "https://reports.example.test/start"}
                          for name in ("one", "two")]}
    with _client(routes, seen) as client:
        result = download_public_pdfs(discovery, tmp_path, client=client, resolver=PUBLIC_IP)
    assert len(result["files"]) == 1
    assert [item["status"] for item in result["file_details"]] == ["downloaded", "duplicate"]
    assert result["file_details"][0]["sha256"] == result["file_details"][1]["sha256"]
    assert "discovery_page" in (tmp_path / "manifest.json").read_text(encoding="utf-8")


def test_nonpublic_redirect_is_rejected_before_request():
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private.pdf"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = PublicPdfCrawler("https://reports.example.test/report.pdf", LIMITS,
                                  client=client, resolver=PUBLIC_IP).discover()
    assert not result["pdfs"]
    assert all("127.0.0.1" not in url for url in seen)


def test_scraped_pdf_document_uses_download_url_as_source(monkeypatch):
    from backend.services import scraper

    captured = []

    async def fake_ingest(filepath, source_url=""):
        captured.append((filepath, source_url))
        return {"document_id": 17, "filename": "report.pdf", "source_kind": "scraped_file"}

    monkeypatch.setattr(scraper, "_ingest_scraped_file", fake_ingest)
    result = asyncio.run(scraper._ingest_scraped_result(
        "https://reports.example.test/annual",
        {"files": ["/tmp/report.pdf"], "file_details": [{
            "path": "/tmp/report.pdf",
            "download_url": "https://cdn.example.test/report.pdf",
            "discovery_page": "https://reports.example.test/annual",
            "sha256": "abc123",
            "downloaded_at": "2026-09-27T00:00:00Z",
        }]},
    ))
    assert captured == [("/tmp/report.pdf", "https://cdn.example.test/report.pdf")]
    assert result["rag_documents"][0]["discovery_page"] == "https://reports.example.test/annual"
    assert result["rag_documents"][0]["sha256"] == "abc123"
