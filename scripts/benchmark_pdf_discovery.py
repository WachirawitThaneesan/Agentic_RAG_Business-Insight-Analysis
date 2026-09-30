"""Score bounded PDF discovery on a frozen list of official report pages."""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from backend.services.pdf_discovery import CrawlLimits, discover_public_pdfs
from backend.services.scraper import _browser_report_links


def _score(site: dict, limits: CrawlLimits, browser: bool) -> dict:
    started = time.perf_counter()
    try:
        result = discover_public_pdfs(site["seed_url"], limits,
                                      _browser_report_links if browser else None)
        url_pattern = re.compile(site.get("expected_url_regex", r"a^"), re.I)
        anchor_pattern = re.compile(site.get("expected_anchor_regex", r"a^"), re.I)
        match = next((pdf for pdf in result["pdfs"] if
                      url_pattern.search(pdf["url"]) or
                      (pdf["discovery_page"] == site["seed_url"] and
                       anchor_pattern.search(pdf["anchor_text"]))), None)
        if match:
            reason = "found"
        elif any(item["reason"] == "robots_disallow" and
                 item["url"] == site["seed_url"] for item in result["blocked"]):
            reason = "robots_disallow"
        elif any(item["stage"] == "page" and item["url"] == site["seed_url"]
                 and item["reason"] == "HTTP 403" for item in result["failures"]):
            reason = "site_http_403"
        elif any(item["stage"] == "pdf_probe" and item["reason"] == "HTTP 403"
                 for item in result["failures"]):
            reason = "pdf_http_403"
        elif result["budget_exhausted"]:
            reason = "time_budget"
        elif not result["visited_pages"] and any(item["stage"] == "robots" for item in result["failures"]):
            reason = "robots_unavailable"
        elif not result["pdfs"]:
            reason = "no_verified_pdf"
        else:
            reason = "expected_report_not_found"
        return {"site": site, "known_found": bool(match), "matched_pdf": match,
                "reason": reason, "seconds": round(time.perf_counter() - started, 2),
                "discovery": result}
    except Exception as exc:
        return {"site": site, "known_found": False, "matched_pdf": None,
                "reason": f"crawler_error: {type(exc).__name__}: {exc}",
                "seconds": round(time.perf_counter() - started, 2), "discovery": None}


def _markdown(rows: list[dict], settings: dict) -> str:
    found = sum(row["known_found"] for row in rows)
    lines = [
        "# Public PDF discovery benchmark", "",
        f"Run: {settings['run_utc']}. Frozen sample: {len(rows)} official report pages.",
        f"Known reports found: **{found}/{len(rows)}**. A hit requires a verified PDF",
        "whose URL matches the predeclared pattern, or whose link label matches on the",
        "official seed page. PDF probes read only the first bytes; no report was ingested.",
        "", "| Publisher | Known report | Verified PDFs | Pages | Browser | Result |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        result = row.get("discovery") or {}
        site = row["site"]
        lines.append(
            f"| [{site['name']}]({site['seed_url']}) | {site['report']} | "
            f"{len(result.get('pdfs', []))} | {len(result.get('visited_pages', []))} | "
            f"{'yes' if result.get('browser_fallback_used') else 'no'} | "
            f"{'found' if row['known_found'] else row['reason']} |"
        )
    lines.extend(["", "## Misses and access limits", ""])
    for row in rows:
        if row["known_found"]:
            continue
        result = row.get("discovery") or {}
        failures = result.get("failures", [])[:3]
        blocked = result.get("blocked", [])[:3]
        details = "; ".join(f"{item.get('stage', item.get('reason'))}: {item.get('reason')}"
                            for item in failures + blocked)
        lines.append(f"- **{row['site']['name']}**: {row['reason']}"
                     + (f" ({details})" if details else ""))
    lines.extend(["", "The test uses fixed page, depth, PDF, time, and sitemap budgets;",
                  "it obeys robots.txt and stays on the seed host for page crawling.",
                  "A miss can reflect site restrictions, PDF hosting behavior, or the crawl budget.",
                  "The machine-readable JSON contains every candidate URL, discovery page,",
                  "blocked URL, failure, and elapsed time.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("TestFile/pdf_discovery_sites_v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site", action="append", help="Run only a named publisher; repeatable")
    parser.add_argument("--browser-fallback", action="store_true")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-pdfs", type=int, default=8)
    parser.add_argument("--max-seconds", type=float, default=25)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sites = [site for site in manifest["sites"] if
             not args.site or site["name"].lower() in {name.lower() for name in args.site}]
    if not sites:
        raise ValueError("No matching benchmark sites")
    limits = CrawlLimits(max_pages=max(1, args.max_pages), max_depth=2,
                         max_sitemaps=1, max_pdfs=max(1, args.max_pdfs),
                         max_seconds=max(5, args.max_seconds),
                         request_delay=0.3, timeout=8)
    rows = [None] * len(sites)
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 5))) as executor:
        pending = {executor.submit(_score, site, limits, args.browser_fallback): i
                   for i, site in enumerate(sites)}
        for future in as_completed(pending):
            index = pending[future]
            rows[index] = future.result()
            row = rows[index]
            print(f"{row['site']['name']}: {row['reason']} ({row['seconds']}s)", flush=True)
    settings = {"run_utc": datetime.now(timezone.utc).isoformat(),
                "manifest": str(args.manifest), "browser_fallback": args.browser_fallback,
                "limits": limits.__dict__}
    payload = {"settings": settings, "known_found": sum(row["known_found"] for row in rows),
               "total_sites": len(rows), "sites": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(rows, settings), encoding="utf-8")
    print(f"Known reports found: {payload['known_found']}/{payload['total_sites']}")


if __name__ == "__main__":
    main()
