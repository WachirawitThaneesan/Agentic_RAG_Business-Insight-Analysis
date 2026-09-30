# Public PDF discovery benchmark

Run: 2026-09-27T06:08:48.879387+00:00. Frozen sample: 20 official report pages.
Known reports found: **17/20**. A hit requires a verified PDF
whose URL matches the predeclared pattern, or whose link label matches on the
official seed page. PDF probes read only the first bytes; no report was ingested.

| Publisher | Known report | Verified PDFs | Pages | Browser | Result |
| --- | --- | ---: | ---: | --- | --- |
| [Bank of Thailand TH](https://www.bot.or.th/th/research-and-publications/reports/annual-report/report-2024.html) | รายงานประจำปี ธปท. 2567 | 20 | 3 | no | found |
| [TPAC TH](https://tpacpackaging.com/th/investor-relations/) | รายงานประจำปี 2567 (56-1 One Report) | 13 | 10 | no | found |
| [CP Axtra TH](https://www.cpaxtra.com/th/investor-relations/document/annual-reports) | แบบแสดงรายการข้อมูลประจำปี 2567 | 7 | 10 | no | found |
| [Central Pattana TH](https://investor.centralpattana.co.th/th/resource-center) | รายงานประจำปี 2567 (56-1 One Report) | 6 | 10 | no | found |
| [Thanachart Capital TH](https://www.thanachart.co.th/th/investor-relations/downloads/yearly-report) | แบบ 56-1 One Report 2567 | 10 | 10 | no | found |
| [PTT TH](https://investor.pttplc.com/th/downloads/yearly-reports?year=2024) | แบบ 56-1 One Report 2567 | 9 | 10 | no | found |
| [AIS TH](https://investor.ais.co.th/th/document/annual-reports) | รายงานประจำปี 2567 (Thai chapter PDF, any chapter) | 13 | 10 | no | found |
| [Stock Exchange of Thailand TH](https://www.set.or.th/th/about/overview/report/annual-report) | รายงานประจำปี 2567 | 10 | 10 | no | found |
| [Thai SEC TH](https://www.sec.or.th/TH/Pages/AboutUs/AnnualReports.aspx) | รายงานประจำปี 2567 | 0 | 10 | yes | site_http_403 |
| [Bangkok Bank TH](https://www.bangkokbank.com/th-TH/Investor-Relations/Financial-Information) | แบบ 56-1 One Report ปี 2567 | 0 | 0 | no | robots_disallow |
| [SCB TH](https://www.scb.co.th/th/shareholders/financial-information) | รายงานประจำปี 2567 | 19 | 10 | no | found |
| [EGCO TH](https://www.egco.com/th/investor-relations/document/annual-reports) | 2024/2567 Thai One Report | 5 | 10 | no | found |
| [IRPC TH](https://irpc.co.th/news-media/publication/) | 2024/2567 Thai One Report | 0 | 10 | yes | site_http_403 |
| [Gulf TH](https://investor.gulf.co.th/th/resource-center) | 2024/2567 Thai One Report | 8 | 10 | no | found |
| [BTS Group TH](https://www.btsgroup.co.th/th/investor-relations/document/yearly-reports) | 2024/25 Thai annual report | 16 | 10 | no | found |
| [PTTGC TH](https://www.pttgcgroup.com/th/investor-relations/document/annual-filings) | 2024/2567 Thai One Report | 5 | 10 | no | found |
| [Thai Union TH](https://investor.thaiunion.com/th/downloads/one-report) | 2024/2567 Thai One Report | 20 | 4 | no | found |
| [SCGP TH](https://investor.scgpackaging.com/th/downloads/yearly-reports?year=2024) | 2024/2567 Thai One Report | 20 | 2 | no | found |
| [SCBX TH](https://investor.scbx.com/th/document/annual-reports) | 2024/2567 Thai annual report | 5 | 10 | no | found |
| [BKI Holdings TH](https://www.bkiholdings.com/investor/Published) | 2024/2567 Thai One Report | 15 | 3 | no | found |

## Misses and access limits

- **Thai SEC TH**: site_http_403 (robots: robots.txt HTTP 403 unavailable; page: HTTP 403; sitemap: HTTP 403)
- **Bangkok Bank TH**: robots_disallow (robots: The read operation timed out; robots_disallow: robots_disallow; robots_disallow: robots_disallow; robots_disallow: robots_disallow)
- **IRPC TH**: site_http_403 (robots: robots.txt HTTP 403 unavailable; page: HTTP 403; sitemap: HTTP 403)

The test uses fixed page, depth, PDF, time, and sitemap budgets;
it obeys robots.txt and stays on the seed host for page crawling.
A miss can reflect site restrictions, PDF hosting behavior, or the crawl budget.
The machine-readable JSON contains every candidate URL, discovery page,
blocked URL, failure, and elapsed time.
