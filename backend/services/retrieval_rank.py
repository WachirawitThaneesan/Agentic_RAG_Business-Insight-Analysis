"""Deterministic Thai keyword ranking and conservative document scoping.

Search normalization is used only for matching. Callers must keep the original
OCR/table text and its page metadata as answer evidence.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Iterable


_GENERIC_FILENAME_WORDS = {
    "annual", "report", "one", "financial", "statement", "pdf", "final",
    "thai", "english", "th", "en", "selected", "page", "pages",
}

_KNOWN_FILENAME_ALIASES = {
    "scbx": ("scbx", "เอสซีบี เอกซ์"),
    "thai_union": ("thai union", "ไทยยูเนี่ยน", "ไทยยูเนียน"),
    "cpaxtra": ("cpaxtra", "cp axtra", "cpaxt", "ซีพี แอ็กซ์ตร้า", "ซีพีแอ็กซ์ตร้า"),
    "egco": ("egco", "เอ็กโก"),
    "ptt": ("ptt", "ปตท.", "ปตท"),
    "pttep": ("pttep", "ปตท.สผ.", "ปตท.สผ", "ปตท. สผ.",
              "ปตท.สำรวจและผลิตปิโตรเลียม", "ปตท. สำรวจและผลิตปิโตรเลียม"),
}


def normalize_search_text(value: str) -> str:
    """Collapse duplicated Thai marks common in selectable PDF text."""
    text = str(value or "")
    # Some Thai PDFs insert one or two Latin glyphs inside a Thai word when a
    # custom font is decoded (for example หนี้Qสิน, เฉลี่Pย, เบี้Ěย). Limit
    # removal to short intrusions between Thai characters; keep real acronyms
    # such as NIM, ROE, EBITDA and SCBX intact.
    text = re.sub(r"(?<=[ก-๙])[A-Za-zÀ-ÿĚ]{1,2}(?=[ก-๙])", "", text)
    text = re.sub(r"(?<=[ก-๙])[�ˠˣ](?=[ก-๙])", "", text)
    try:
        from pythainlp.util import normalize as thai_normalize
    except ImportError:
        return text
    return thai_normalize(text)


@lru_cache(maxsize=20000)
def search_tokens(value: str) -> tuple[str, ...]:
    text = normalize_search_text(value)
    try:
        from pythainlp.tokenize import word_tokenize
        parts = word_tokenize(text, engine="newmm", keep_whitespace=False)
    except ImportError:
        parts = re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?|[ก-๙]+", text)
    return tuple(token.casefold() for token in parts
                 if re.fullmatch(r"[A-Za-z]+|\d+(?:\.\d+)?|[ก-๙]+", token))


def _document_aliases(filename: str) -> list[str]:
    stem = re.sub(r"\.pdf$", "", str(filename or ""), flags=re.IGNORECASE)
    stem_key = re.sub(r"[^a-z0-9]+", "_", stem.casefold()).strip("_")
    aliases = [alias for key, values in _KNOWN_FILENAME_ALIASES.items()
               if re.search(r"(?:^|_)" + re.escape(key) + r"(?:_|$)", stem_key)
               for alias in values]
    latin_words = re.findall(r"[a-z0-9]+", stem_key)
    aliases.extend(token for token in latin_words
                   if len(token) >= 3 and token not in _GENERIC_FILENAME_WORDS
                   and not re.fullmatch(r"(?:25|20)\d{2}", token))
    return aliases


def matched_document_aliases(
    question: str, documents: Iterable[tuple[int, str]],
) -> tuple[set[int] | None, tuple[str, ...]]:
    """Return explicitly named documents and the matched issuer expressions.

    Unknown names return None, keeping all documents eligible. The short alias
    list covers issuer spellings seen in diagnostics; other issuers can still be
    matched by a distinctive Latin filename token.
    """
    query = normalize_search_text(question).casefold()
    occurrences: list[tuple[int, int, int, str]] = []
    for document_id, filename in documents:
        for alias in _document_aliases(filename):
            needle = normalize_search_text(alias).casefold()
            pattern = re.escape(needle)
            if re.fullmatch(r'[a-z0-9 ]+', needle):
                pattern = r'(?<![a-z0-9])' + pattern + r'(?![a-z0-9])'
            for match in re.finditer(pattern, query):
                occurrences.append((match.start(), match.end(), int(document_id), alias))
    # A subsidiary name can contain the parent's abbreviation. Prefer the
    # longer mention at the same location; retain separately named companies.
    # Never decide document scope using evaluation metadata or target pages.
    retained = [row for row in occurrences if not any(
        other[0] <= row[0] and other[1] >= row[1]
        and other[1] - other[0] > row[1] - row[0]
        for other in occurrences)]
    chosen = {row[2] for row in retained}
    matched = {row[3] for row in retained}
    return chosen or None, tuple(sorted(matched, key=len, reverse=True))


def mentioned_document_ids(question: str, documents: Iterable[tuple[int, str]]) -> set[int] | None:
    return matched_document_aliases(question, documents)[0]


def without_document_aliases(question: str, aliases: Iterable[str]) -> str:
    """Keep the issuer for document scope but omit it from evidence ranking.

    A repeated company name otherwise outranks the requested metric. Use only
    aliases actually matched to the selected document, preserving other terms.
    """
    result = normalize_search_text(question)
    for alias in aliases:
        pattern = re.escape(normalize_search_text(alias))
        if re.fullmatch(r'[a-z0-9 ]+', alias, re.I):
            pattern = r'(?<![a-z0-9])' + pattern + r'(?![a-z0-9])'
        result = re.sub(pattern, " ", result,
                        flags=re.IGNORECASE)
    return result.strip() or question


def bm25_rank(question: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank a bounded candidate set without changing the cited source text."""
    terms = set(search_tokens(question))
    if not terms or not rows:
        return []
    counters = [Counter(search_tokens(row.get("search_text") or row.get("text") or ""))
                for row in rows]
    lengths = [sum(counter.values()) for counter in counters]
    average = sum(lengths) / len(lengths) or 1.0
    df = Counter(token for counter in counters for token in counter)
    n = len(rows)
    scored: list[tuple[float, int]] = []
    for index, (counter, length) in enumerate(zip(counters, lengths)):
        score = 0.0
        for term in terms:
            freq = counter.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * freq * 2.5 / (
                freq + 1.5 * (0.25 + 0.75 * length / average)
            )
        if score > 0:
            scored.append((score, index))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [{**rows[index], "keyword_score": score} for score, index in scored]


@lru_cache(maxsize=8)
def _repeated_prefix_spans(first_pages: tuple[tuple[int, str], ...]) -> tuple[str, ...]:
    """Find long navigation blocks repeated on most pages of a document.

    Restrict discovery to the first 1200 characters, require at least 20
    physical pages and 60% prevalence. This cannot erase ordinary repeated
    financial labels. Numbers and original evidence are never rewritten.
    """
    if len(first_pages) < 20:
        return ()
    # Match anchor spans at any offset on other pages. Fixed window offsets
    # would miss the same sidebar after a variable-length section heading.
    seeds = {round(i * (len(first_pages) - 1) / 4) for i in range(5)}
    anchors = {text[i:i + 160] for index in seeds
               for text in (first_pages[index][1][:1200],)
               for i in range(0, max(0, len(text) - 159), 10)}
    prefixes = [text[:1200] for _, text in first_pages]
    threshold = max(20, math.ceil(len(first_pages) * 0.6))
    return tuple(sorted(span for span in anchors if sum(span in prefix for prefix in prefixes) >= threshold))


def remove_repeated_navigation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Suppress long repeated PDF navigation only in lexical search text.

    Corpus evidence, embeddings, filenames, page numbers and quotations remain
    untouched. Insufficient document coverage causes no suppression.
    """
    by_document: dict[Any, dict[Any, dict[str, Any]]] = {}
    for row in rows:
        if row.get('page') is None or row.get('document_id') is None:
            continue
        pages = by_document.setdefault(row['document_id'], {})
        prior = pages.get(row['page'])
        if prior is None or row.get('chunk_index', row.get('chunk_id', 0)) < prior.get('chunk_index', prior.get('chunk_id', 0)):
            pages[row['page']] = row
    patterns = {}
    for doc, pages in by_document.items():
        first = tuple(sorted((int(page), str(row.get('search_text') or row.get('text') or ''))
                             for page, row in pages.items()))
        spans = _repeated_prefix_spans(first)
        if spans:
            patterns[doc] = spans
    result = []
    for row in rows:
        spans = patterns.get(row.get('document_id'))
        if not spans:
            result.append(row); continue
        value = str(row.get('search_text') or row.get('text') or '')
        # Merge overlapping spans before replacement so a removed fragment
        # cannot hide the overlap of the next detected navigation fragment.
        intervals = []
        for span in spans:
            start = value.find(span)
            if 0 <= start < 1200:
                intervals.append((start, start + len(span)))
        merged: list[list[int]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:merged[-1][1] = max(merged[-1][1], end)
            else:merged.append([start, end])
        for start, end in reversed(merged):value = value[:start] + ' ' + value[end:]
        result.append({**row, 'search_text': value or ' ', 'navigation_spans_removed': len(merged)})
    return result


def unique_pages(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give each physical PDF page one slot in an evidence ranking."""
    seen = set()
    result = []
    for row in rows:
        document_id, page = row.get("document_id"), row.get("page")
        key = (document_id, page) if document_id is not None and page is not None else (
            "chunk", row.get("chunk_id"))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
