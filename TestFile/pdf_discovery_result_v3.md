# Public PDF discovery benchmark

Run: 2026-09-26T18:16:55.017420+00:00. Frozen sample: 20 official report pages.
Known reports found: **14/20**. A hit requires a verified PDF
whose URL matches the predeclared pattern, or whose link label matches on the
official seed page. PDF probes read only the first bytes; no report was ingested.

| Publisher | Known report | Verified PDFs | Pages | Browser | Result |
| --- | --- | ---: | ---: | --- | --- |
| [BIS](https://www.bis.org/about/areport/areport2024.htm) | Annual Report 2023/24 | 1 | 5 | no | found |
| [ADB](https://www.adb.org/documents/adb-annual-report-2024) | ADB Annual Report 2024 main report | 2 | 5 | no | found |
| [Bank of Thailand](https://www.bot.or.th/en/research-and-publications/reports/annual-report.html) | Annual Report 2024 | 8 | 1 | no | found |
| [World Bank](https://www.worldbank.org/en/about/annual-report/world-bank-group-downloads) | World Bank Group Annual Report 2025 | 4 | 1 | no | found |
| [UNICEF](https://www.unicef.org/reports/unicef-annual-report/2024) | UNICEF Annual Report 2024 English | 4 | 5 | no | found |
| [UNDP Thailand](https://www.undp.org/thailand/publications/annual-report-2024) | UNDP Thailand Annual Report 2024 | 1 | 5 | no | found |
| [WHO](https://www.who.int/publications/b/78941) | TDR Annual Report 2024 | 4 | 5 | no | robots_unavailable |
| [IMF](https://www.elibrary.imf.org/abstract/book/9798400279300/9798400279300.xml) | IMF Annual Report 2024 | 3 | 5 | yes | found |
| [ECB](https://www.ecb.europa.eu/press/annual-reports-financial-statements/annual/html/ecb.ar2024~8402d8191f.en.html) | ECB Annual Report 2024 | 8 | 1 | no | found |
| [UNHCR](https://www.unhcr.org/media/global-report-2024) | Global Report 2024 | 0 | 5 | yes | site_http_403 |
| [OECD](https://www.oecd.org/en/networks/global-forum-tax-transparency/resources/publications-and-documents-archive.html) | Global Forum Annual Report 2024 | 0 | 5 | yes | site_http_403 |
| [UNESCO](https://www.unesco.org/reports/gem-report/en/2024) | Global Education Monitoring Report 2024/5 | 0 | 5 | yes | site_http_403 |
| [ILO](https://www.ilo.org/publications/flagship-reports/world-employment-and-social-outlook-trends-2024) | World Employment and Social Outlook: Trends 2024 | 4 | 5 | no | found |
| [WTO](https://www.wto.org/english/res_e/publications_e/anrep24_e.htm) | WTO Annual Report 2024 | 8 | 4 | no | found |
| [WFP](https://www.wfp.org/publications/annual-performance-report) | Annual Performance Report 2024 English | 0 | 5 | yes | pdf_http_403 |
| [EBRD](https://www.ebrd.com/home/news-and-events/publications/annual-review.html) | Annual Review 2024 | 8 | 1 | no | found |
| [EIB](https://www.eib.org/en/publications/online/all/activity-report-2024) | EIB Group Activity Report 2024 | 8 | 2 | no | found |
| [PTT](https://investor.pttplc.com/en/downloads/yearly-reports?year=2024) | Form 56-1 One Report 2024 | 6 | 5 | no | found |
| [NVIDIA](https://investor.nvidia.com/financial-info/annual-reports-and-proxies/default.aspx) | NVIDIA 2024 Annual Report | 8 | 1 | yes | found |
| [Unilever](https://www.unilever.com/investors/annual-report-and-accounts/) | Annual Report and Accounts 2024 | 0 | 5 | yes | site_http_403 |

## Misses and access limits

- **WHO**: robots_unavailable (robots: timed out; robots: robots.txt HTTP 403 unavailable; robots_disallow: robots_disallow; robots_disallow: robots_disallow; robots_disallow: robots_disallow)
- **UNHCR**: site_http_403 (robots: robots.txt HTTP 403 unavailable; page: HTTP 403; sitemap: HTTP 403)
- **OECD**: site_http_403 (page: HTTP 403; sitemap: HTTP 403; page: HTTP 403)
- **UNESCO**: site_http_403 (robots: robots.txt HTTP 403 unavailable; page: HTTP 403; sitemap: HTTP 403; robots_disallow: robots_disallow)
- **WFP**: pdf_http_403 (robots: robots.txt HTTP 403 unavailable; pdf_probe: HTTP 403; pdf_probe: HTTP 403)
- **Unilever**: site_http_403 (robots: robots.txt HTTP 403 unavailable; page: HTTP 403; sitemap: HTTP 403)

The test uses fixed page, depth, PDF, time, and sitemap budgets;
it obeys robots.txt and stays on the seed host for page crawling.
A miss can reflect site restrictions, PDF hosting behavior, or the crawl budget.
The machine-readable JSON contains every candidate URL, discovery page,
blocked URL, failure, and elapsed time.
