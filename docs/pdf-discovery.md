# Public PDF discovery (Step 7)

The public collection path starts with bounded HTTP crawling of a supplied report
page. It follows same-host report links, reads robots.txt and sitemaps, and checks
linked PDF bytes even when a URL does not end in `.pdf`. For PDF-only collection,
it renders the seed page with Playwright only if HTTP and sitemap crawling found
no PDF. Keyword search uses Playwright to find seed URLs, then runs this same
crawler for each result. Explicit image-download requests use the legacy browser
worker.
Valid robots disallow rules are honored; a 4xx `robots.txt` response is treated as
an unavailable policy under [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html).
The crawler does not bypass page or download HTTP 403 responses.

`POST /api/scrape/discover` returns verified links, visited pages, failed probes,
blocked URLs, and elapsed checks without downloading reports. For example:

```json
{"url":"https://www.bot.or.th/th/research-and-publications/reports/annual-report/report-2024.html","max_pages":10,"max_depth":2,"max_pdfs":20,"max_seconds":90,"browser_fallback":true}
```

`POST /api/scrape/url` downloads verified PDFs by default and queues them through
the same ingestion path as uploads. Each run writes `scrape_output/<site>_<time>/manifest.json`
with the discovery page, final download URL, UTC timestamp, SHA-256 hash, size,
and downloaded/duplicate/failed status. The PDF document's `source_url` is the
final download URL. Public collection is disabled when `OFFLINE_MODE=true`.

## Measured discovery

The primary language-relevant run used [20 official Thai report pages](../TestFile/pdf_discovery_thai_sites_v5.json)
on 2026-09-27. The final run found **17/20** predeclared Thai annual reports or Thai
report chapters as byte-verified PDFs. The [full result](../TestFile/pdf_discovery_thai_result_v7.json)
and [readable table](../TestFile/pdf_discovery_thai_result_v7.md) preserve
every candidate, page visited, elapsed time, and failure. It used at most 10
pages, 20 verified PDFs, and 90 seconds per site, with browser fallback.
The direct BTS result was downloaded separately and its first five pages
contained 7,293 Thai characters versus 696 Latin letters; its PDF has 226
physical pages. Other hits were selected by official Thai report labels and
Thai PDF filenames; the benchmark did not inspect the full text of every hit.

| Miss | Observed limit |
| --- | --- |
| Bangkok Bank | `robots.txt` disallowed the seed page. |
| Thai SEC, IRPC | The seed pages returned HTTP 403 in this environment; browser fallback did not recover them. |

The crawler now follows PDF URLs embedded in HTML viewers that end in `.pdf`,
which recovered CP Axtra, Central Pattana, EGCO, Gulf, and SCBX reports. It
also inspects bounded static flipbook URLs assembled in page scripts, which
recovered PTT Global Chemical. It prioritizes recent annual-report links when
an archive exposes many PDFs.
The first 11-site Thai run found 6/11; subsequent saved runs show the viewer
fix and a correction to the AIS target label. AIS publishes 2567 as multiple
Thai chapter PDFs, so the final label accepts any 2024 Thai chapter. These
benchmark-label revisions are preserved in the `v2`–`v5` Thai manifests and
`v2`–`v7` result files. They should not be interpreted as independent samples.

The earlier **English-language pilot** is retained below for comparison only.
It is not evidence of Thai-report discovery quality.

On 2026-09-27, the corrected [20-page official publisher sample](../TestFile/pdf_discovery_sites_v3.json)
produced **14/20 known reports found** with HTTP first and Playwright fallback.
The [full result](../TestFile/pdf_discovery_result_v3.json) and
[readable table](../TestFile/pdf_discovery_result_v3.md) record each candidate,
failure, browser use, and elapsed time. Browser rendering was used on seven
sites; it recovered IMF and NVIDIA reports. The earlier HTTP-only run found
**12/20** ([raw result](../TestFile/pdf_discovery_http_v2.json)). The v3 label
correction changed NVIDIA's expected filename; it did not affect the HTTP-only
score because that site returned HTTP 403 to plain HTTP.

| Miss | Observed limit |
| --- | --- |
| WHO | Across runs, robots.txt fetch errors, a target link that did not verify as PDF, and time exhaustion while probing other PDFs were observed. |
| UNHCR, OECD, UNESCO, Unilever | Their report pages returned HTTP 403 here; browser fallback did not recover the report. |
| WFP | The linked document host returned HTTP 403 for PDF downloads. |

These numbers are discovery hits on a small, chosen set of known report pages,
not a general success rate. A hit requires a byte-verified PDF whose URL or
seed-page link label matches the frozen report label. PDF probes read only the
first bytes; they do not prove full download or OCR quality. Separate live
downloads did complete for the ILO full report (2,860,492 bytes) and the World
Bank Group 2025 annual report (11,243,902 bytes), with hashes and source pages
saved in their run manifests. The World Bank PDF cover was checked against the
target year.

The first [v1 sample](../TestFile/pdf_discovery_sites_v1.json) was preserved for
audit. Its Microsoft link was a DOCX, its World Bank PDF had an opaque URL, and
its ILO seed page was an executive summary. The
[v2 sample](../TestFile/pdf_discovery_sites_v2.json) corrected those entries.
The v3 sample then corrected NVIDIA's current 2024 PDF filename after inspecting
the official rendered page. These revisions are recorded rather than silently
changing the original sample.

To repeat the Thai benchmark from the repository root:

```powershell
python -m scripts.benchmark_pdf_discovery --manifest TestFile/pdf_discovery_thai_sites_v5.json --output TestFile/pdf_discovery_thai_repeat.json --workers 3 --max-pages 10 --max-pdfs 20 --max-seconds 90 --browser-fallback
```

To repeat the earlier English benchmark:

```powershell
python -m scripts.benchmark_pdf_discovery --manifest TestFile/pdf_discovery_sites_v3.json --output TestFile/pdf_discovery_repeat.json --workers 3 --max-pages 5 --max-seconds 85 --browser-fallback
```

The benchmark is read-only: it does not ingest reports. Web pages, links, and
access rules can change, so a later run may differ. The 85-second limit is a
per-site crawl budget; a slow request can finish slightly after that limit.
Current gaps are PDF relevance ranking on pages with many unrelated links and
sites that block ordinary HTTP or PDF downloads.
