"""Bounded, polite discovery and download of publicly linked PDF reports."""

from __future__ import annotations

import hashlib
import gzip
import ipaddress
import json
import re
import socket
import time
import xml.etree.ElementTree as ET
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "BusinessInsightResearchBot/1.0 (+public-report-discovery)"
REPORT_HINT = re.compile(
    r"report|annual|financial|publication|document|investor|sustainab|"
    r"download|attachment|filing|รายงาน|งบการเงิน|ดาวน์โหลด|แบบแสดง",
    re.IGNORECASE,
)
PDF_HINT = re.compile(r"\.pdf(?:$|[/?#])|\bpdf\b|\bdownload\b|getmedia|/attachment(?:/|$)", re.I)
INLINE_PDF_URL = re.compile(r"https?://[^\s\"'<>`\\]+?\.pdf(?:\?[^\s\"'<>`\\#]*)?", re.I)
INLINE_VIEWER_URL = re.compile(
    r"https?://[^\s\"'<>`\\]+/(?:flipbook|viewer)(?:#[^\s\"'<>`\\]*)?", re.I
)
ANNUAL_HINT = re.compile(r"annual|one[-_ ]?report|รายงานประจำปี|56[- ]?1", re.I)
THAI_HINT = re.compile(r"(?:/th/|[_-]th(?:\.|[_-])|รายงานประจำปี|งบการเงิน)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _public_url(url: str, resolver: Callable[[str], list[str]]) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return False
    host = parts.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return False
    try:
        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    try:
        addresses = resolver(host)
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(value).is_global for value in addresses)


@lru_cache(maxsize=256)
def _resolve(host: str) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, None)})


@dataclass(frozen=True)
class CrawlLimits:
    max_pages: int = 20
    max_depth: int = 2
    max_sitemaps: int = 3
    max_pdfs: int = 20
    max_seconds: float = 90.0
    request_delay: float = 0.4
    timeout: float = 12.0
    max_html_bytes: int = 2_000_000
    max_sitemap_bytes: int = 3_000_000


class PublicPdfCrawler:
    def __init__(
        self, seed_url: str, limits: CrawlLimits = CrawlLimits(),
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] = _resolve,
    ) -> None:
        self.seed_url = _clean_url(seed_url)
        self.limits = limits
        self.resolver = resolver
        self.client = client or httpx.Client(timeout=limits.timeout, follow_redirects=False,
                                             headers={"User-Agent": USER_AGENT}, trust_env=False)
        self._owns_client = client is None
        self.host = urlsplit(self.seed_url).hostname or ""
        if not _public_url(self.seed_url, resolver):
            raise ValueError("Discovery requires a public HTTP(S) URL")
        self._started = time.monotonic()
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_sitemaps: list[str] = []
        self._queue: deque[tuple[str, int, str, str]] = deque()
        self._queued: set[str] = set()
        self._seen: set[str] = set()
        self._pdf_seen: set[str] = set()
        self._pdf_probes = 0
        self._sitemap_seen: set[str] = set()
        self.pdfs: list[dict] = []
        self.blocked: list[dict] = []
        self.failures: list[dict] = []
        self.root_text = ""
        self.browser_fallback_used = False
        self._queue_page(self.seed_url, 0, self.seed_url, "seed")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _same_site(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host == self.host or host.removeprefix("www.") == self.host.removeprefix("www.")

    def _budget_ok(self) -> bool:
        return time.monotonic() - self._started < self.limits.max_seconds

    def _link_priority(self, url: str, label: str) -> int:
        context = f"{url} {label}"
        score = 10 if ANNUAL_HINT.search(context) else 0
        years = [int(value) for value in re.findall(r"(?<!\d)(?:20\d{2}|25\d{2})(?!\d)", context)]
        if years:
            # Report archives commonly expose many years. Spend bounded page
            # and PDF budgets on recent reports before old flipbook viewers.
            ad_year = max(value - 543 if value >= 2500 else value for value in years)
            score += max(0, min(ad_year, datetime.now(timezone.utc).year) - 2010)
        if "/document/viewer/" in url:
            score += 3
        if THAI_HINT.search(context):
            score += 2 if "/th/" in self.seed_url else 1
        if "/en/" in url and "/th/" in self.seed_url:
            score -= 5
        if "factsheet" in context.casefold():
            score -= 3
        return score

    def _request(self, url: str, *, max_bytes: int, sample_only: bool = False,
                 check_redirect_robots: bool = True) -> tuple[httpx.Response, bytes, str]:
        current = url
        for _ in range(6):
            if not self._budget_ok():
                raise TimeoutError("Crawl time budget exhausted")
            if not _public_url(current, self.resolver):
                raise ValueError("Non-public URL or redirect blocked")
            host = urlsplit(current).hostname or ""
            delay = self.limits.request_delay
            robots = self._robots.get(host)
            if robots is not None:
                delay = max(delay, float(robots.crawl_delay(USER_AGENT) or 0))
            pause = self._last_request.get(host, 0) + delay - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            self._last_request[host] = time.monotonic()
            with self.client.stream("GET", current, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect missing Location")
                    current = _clean_url(urljoin(current, location))
                    if check_redirect_robots and not self._allowed(current):
                        raise ValueError("Redirect target blocked by robots or URL policy")
                    continue
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=min(max_bytes, 65536)):
                    if not data and (b"%PDF-" in chunk[:1024] or
                                     "application/pdf" in response.headers.get("content-type", "").lower()):
                        return response, chunk[:1024], current
                    remaining = max_bytes - len(data)
                    data.extend(chunk[:remaining] if sample_only else chunk)
                    if sample_only and len(data) >= max_bytes:
                        break
                    if len(data) > max_bytes:
                        raise ValueError(f"Response exceeds {max_bytes} byte crawl limit")
                return response, bytes(data), current
        raise ValueError("Too many redirects")

    def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if host in self._robots:
            return self._robots[host]
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response, body, _ = self._request(robots_url, max_bytes=300_000,
                                              check_redirect_robots=False)
            if 400 <= response.status_code < 500:
                # RFC 9309 section 2.3.1.3: a 4xx robots response is unavailable.
                self.failures.append({"url": robots_url, "stage": "robots",
                                      "reason": f"robots.txt HTTP {response.status_code} unavailable"})
                self._robots[host] = None
                return None
            if response.status_code != 200:
                raise ValueError(f"robots.txt HTTP {response.status_code}")
            text = body.decode("utf-8", errors="replace")
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            self._robots[host] = parser
            for line in text.splitlines():
                if line.lower().startswith("sitemap:"):
                    self._robots_sitemaps.append(_clean_url(line.split(":", 1)[1].strip()))
            return parser
        except Exception as exc:
            # An unavailable robots policy is recorded and the site is skipped.
            self.failures.append({"url": robots_url, "stage": "robots", "reason": str(exc)[:200]})
            deny = RobotFileParser()
            deny.parse(["User-agent: *", "Disallow: /"])
            self._robots[host] = deny
            return deny

    def _allowed(self, url: str) -> bool:
        if not _public_url(url, self.resolver):
            self.blocked.append({"url": url, "reason": "non_public_url"})
            return False
        policy = self._robots_for(url)
        if policy is not None and not policy.can_fetch(USER_AGENT, url):
            self.blocked.append({"url": url, "reason": "robots_disallow"})
            return False
        return True

    def _queue_page(self, url: str, depth: int, source: str, label: str,
                    front: bool = False) -> None:
        url = _clean_url(url)
        if (depth > self.limits.max_depth or url in self._queued or not self._same_site(url)
                or not urlsplit(url).scheme.startswith("http")):
            return
        if front:
            self._queue.appendleft((url, depth, source, label))
        else:
            self._queue.append((url, depth, source, label))
        self._queued.add(url)

    def _add_pdf(self, url: str, source: str, label: str, *,
                 viewer_depth: int = 0, via_viewer: str | None = None) -> None:
        url = _clean_url(url)
        if (url in self._pdf_seen or len(self.pdfs) >= self.limits.max_pdfs
                or self._pdf_probes >= self.limits.max_pdfs * 8):
            return
        self._pdf_seen.add(url)
        self._pdf_probes += 1
        if not self._allowed(url):
            return
        try:
            response, data, final_url = self._request(url, max_bytes=4096, sample_only=True)
            if response.status_code not in {200, 206}:
                raise ValueError(f"HTTP {response.status_code}")
            if b"%PDF-" not in data[:1024]:
                if viewer_depth < 2 and b"<html" in data[:1024].lower():
                    soup = BeautifulSoup(data, "html.parser")
                    embedded = [tag.get("src", "") for tag in soup.select("[src]")
                                if ".pdf" in tag.get("src", "").lower()]
                    if embedded:
                        for href in embedded[:3]:
                            self._add_pdf(urljoin(final_url, href), source, label,
                                          viewer_depth=viewer_depth + 1,
                                          via_viewer=final_url)
                        return
                raise ValueError("Response is not a PDF")
            record = {"url": final_url, "discovery_page": source,
                      "anchor_text": label[:200], "status": "verified_pdf",
                      "content_type": response.headers.get("content-type", "")}
            if via_viewer:
                record["via_viewer"] = via_viewer
            self.pdfs.append(record)
        except Exception as exc:
            self.failures.append({"url": url, "stage": "pdf_probe", "reason": str(exc)[:200]})

    def _add_link(self, url: str, source: str, label: str, depth: int) -> None:
        if not url:
            return
        full = _clean_url(urljoin(source, url))
        if urlsplit(full).scheme not in {"http", "https"}:
            return
        context = f"{full} {label}"
        if PDF_HINT.search(context):
            self._add_pdf(full, source, label)
            # A download-looking URL may actually be an HTML report page.
            if (self._same_site(full) and REPORT_HINT.search(context)
                    and not urlsplit(full).path.lower().endswith(".pdf")):
                self._queue_page(full, depth, source, label, front=True)
        elif REPORT_HINT.search(context):
            self._queue_page(full, depth, source, label)

    def _read_sitemaps(self) -> None:
        root = urlsplit(self.seed_url)
        for sitemap in self._robots_sitemaps + [f"{root.scheme}://{root.netloc}/sitemap.xml"]:
            if len(self._sitemap_seen) >= self.limits.max_sitemaps or not self._budget_ok():
                break
            self._read_sitemap(sitemap)

    def _read_sitemap(self, url: str) -> None:
        url = _clean_url(url)
        if (url in self._sitemap_seen or len(self._sitemap_seen) >= self.limits.max_sitemaps
                or not self._same_site(url) or not self._allowed(url)):
            return
        self._sitemap_seen.add(url)
        try:
            response, body, _ = self._request(url, max_bytes=self.limits.max_sitemap_bytes)
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}")
            root = ET.fromstring(gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body)
            tag = root.tag.rsplit("}", 1)[-1].lower()
            locations = [node.text.strip() for node in root.iter()
                         if node.tag.rsplit("}", 1)[-1].lower() == "loc" and node.text]
            if tag == "sitemapindex":
                for child in locations[: self.limits.max_sitemaps]:
                    self._read_sitemap(child)
            elif tag == "urlset":
                for location in locations[:5000]:
                    if PDF_HINT.search(location) or REPORT_HINT.search(location):
                        self._add_link(location, url, "sitemap", 1)
            else:
                raise ValueError("Not a sitemap XML document")
        except Exception as exc:
            self.failures.append({"url": url, "stage": "sitemap", "reason": str(exc)[:200]})

    def _crawl_queue(self) -> None:
        while (self._queue and len(self._seen) < self.limits.max_pages and self._budget_ok()
               and len(self.pdfs) < self.limits.max_pdfs):
            url, depth, _source, _label = self._queue.popleft()
            if url in self._seen or not self._allowed(url):
                continue
            self._seen.add(url)
            try:
                response, body, final_url = self._request(url, max_bytes=self.limits.max_html_bytes)
                if response.status_code != 200:
                    raise ValueError(f"HTTP {response.status_code}")
                if b"%PDF-" in body[:1024]:
                    self._add_pdf(url, url, "direct PDF")
                    continue
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type and b"<html" not in body[:2000].lower():
                    raise ValueError(f"Non-HTML page: {content_type}")
                soup = BeautifulSoup(body, "html.parser")
                if url == self.seed_url:
                    self.root_text = soup.get_text(" ", strip=True)[:5000]
                # Check embedded report PDFs before attachments on the page.
                for frame in soup.select("iframe[src]")[:20]:
                    self._add_link(frame.get("src", ""), final_url, "embedded PDF", depth + 1)
                for script in soup.select("script:not([src])")[:50]:
                    script_text = (script.string or "")[:200_000]
                    for match in list(INLINE_PDF_URL.finditer(script_text))[:20]:
                        self._add_pdf(match.group(0).replace("\\/", "/"), final_url,
                                      "viewer PDF")
                    for match in list(INLINE_VIEWER_URL.finditer(script_text))[:3]:
                        self._add_pdf(match.group(0).replace("\\/", "/"), final_url,
                                      "script viewer")
                anchors = []
                for anchor in soup.select("a[href]"):
                    label = anchor.get_text(" ", strip=True)
                    if not label and anchor.find_parent("tr"):
                        label = anchor.find_parent("tr").get_text(" ", strip=True)
                    anchors.append((anchor.get("href", ""), label[:200]))
                # Put annual reports ahead of factsheets and quarterly files
                # when a page exposes more PDFs than the crawl budget allows.
                page_pdf_probes = self._pdf_probes
                for href, label in sorted(anchors,
                                          key=lambda entry: self._link_priority(*entry),
                                          reverse=True):
                    full = urljoin(final_url, href)
                    if (PDF_HINT.search(f"{full} {label}") and
                            self._pdf_probes - page_pdf_probes >= max(8, self.limits.max_pdfs // 2)):
                        if self._same_site(full) and REPORT_HINT.search(f"{full} {label}"):
                            self._queue_page(full, depth + 1, final_url, label, front=True)
                    else:
                        self._add_link(href, final_url, label, depth + 1)
                for link in soup.select("link[rel][href]"):
                    if "alternate" in (link.get("rel") or []):
                        self._add_link(link.get("href", ""), final_url, "alternate", depth + 1)
                self._queue = deque(sorted(
                    self._queue,
                    key=lambda entry: self._link_priority(entry[0], entry[3]),
                    reverse=True,
                ))
            except Exception as exc:
                self.failures.append({"url": url, "stage": "page", "reason": str(exc)[:200]})

    def discover(self, browser_links: Callable[[str], list[dict]] | None = None) -> dict:
        try:
            self._robots_for(self.seed_url)
            self._crawl_queue()
            if self._budget_ok() and len(self.pdfs) < self.limits.max_pdfs:
                self._read_sitemaps()
                self._crawl_queue()
            if not self.pdfs and browser_links and self._budget_ok() and self._allowed(self.seed_url):
                self.browser_fallback_used = True
                try:
                    for link in browser_links(self.seed_url):
                        self._add_link(link.get("url", ""), self.seed_url,
                                       link.get("text", ""), 1)
                    self._crawl_queue()
                except Exception as exc:
                    self.failures.append({"url": self.seed_url, "stage": "browser", "reason": str(exc)[:200]})
            return {"seed_url": self.seed_url, "pdfs": self.pdfs,
                    "visited_pages": list(self._seen), "sitemaps_checked": list(self._sitemap_seen),
                    "blocked": self.blocked, "failures": self.failures,
                    "browser_fallback_used": self.browser_fallback_used,
                    "budget_exhausted": not self._budget_ok(), "page_text": self.root_text,
                    "checked_at": _now()}
        finally:
            self.close()


def discover_public_pdfs(seed_url: str, limits: CrawlLimits = CrawlLimits(),
                         browser_links: Callable[[str], list[dict]] | None = None) -> dict:
    return PublicPdfCrawler(seed_url, limits).discover(browser_links)


def download_public_pdfs(discovery: dict, folder: str | Path, max_files: int = 20,
                         max_bytes: int = 250_000_000,
                         client: httpx.Client | None = None,
                         resolver: Callable[[str], list[str]] = _resolve) -> dict:
    """Download verified candidates, hash them, and keep a run manifest."""
    output = Path(folder)
    output.mkdir(parents=True, exist_ok=True)
    files_dir = output / "files"
    files_dir.mkdir(exist_ok=True)
    details: list[dict] = []
    seen_hashes: set[str] = set()
    files: list[str] = []
    client_context = (nullcontext(client) if client is not None else
                      httpx.Client(timeout=30, follow_redirects=False,
                                   headers={"User-Agent": USER_AGENT}, trust_env=False))
    with client_context as active_client:
        for item in discovery.get("pdfs", [])[:max_files]:
            url = item["url"]
            record = {"download_url": url, "discovery_page": item["discovery_page"],
                      "downloaded_at": _now(), "status": "failed"}
            temp = files_dir / f"pending_{len(details)}.part"
            try:
                digest = hashlib.sha256()
                size = 0
                prefix = bytearray()
                current = url
                for redirect_count in range(6):
                    if not _public_url(current, resolver):
                        raise ValueError("Download URL is not public")
                    with active_client.stream("GET", current, follow_redirects=False) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            next_url = _clean_url(urljoin(current, response.headers.get("location", "")))
                            if (not response.headers.get("location") or
                                    urlsplit(next_url).hostname != urlsplit(url).hostname):
                                raise ValueError("Download redirect left verified host")
                            current = next_url
                            continue
                        response.raise_for_status()
                        with temp.open("wb") as target:
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > max_bytes:
                                    raise ValueError("PDF exceeds configured size limit")
                                if len(prefix) < 1024:
                                    prefix.extend(chunk[:1024 - len(prefix)])
                                digest.update(chunk)
                                target.write(chunk)
                        record["download_url"] = str(response.url)
                        break
                else:
                    raise ValueError("Too many download redirects")
                if b"%PDF-" not in prefix:
                    raise ValueError("Downloaded content is not a PDF")
                sha = digest.hexdigest()
                record.update({"sha256": sha, "bytes": size})
                if sha in seen_hashes:
                    record["status"] = "duplicate"
                    temp.unlink(missing_ok=True)
                else:
                    name = unquote(Path(urlsplit(record["download_url"]).path).name)
                    name = re.sub(r"[^\w.\-]+", "_", name)[:100].strip("._")
                    if not name.lower().endswith(".pdf"):
                        name = (name or "report") + ".pdf"
                    path = files_dir / f"{sha[:16]}_{name}"
                    if path.exists():
                        temp.unlink(missing_ok=True)
                        record["status"] = "duplicate"
                    else:
                        temp.replace(path)
                        record["status"] = "downloaded"
                    record["path"] = str(path)
                    files.append(str(path))
                    seen_hashes.add(sha)
            except Exception as exc:
                temp.unlink(missing_ok=True)
                record["reason"] = str(exc)[:200]
            details.append(record)
    manifest = {"seed_url": discovery.get("seed_url"), "checked_at": discovery.get("checked_at"),
                "discovery": discovery, "downloads": details}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"files": files, "file_details": details, "manifest_path": str(manifest_path)}
