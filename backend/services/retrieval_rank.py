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
    "cpaxtra": ("cpaxtra", "cp axtra", "ซีพี แอ็กซ์ตร้า", "ซีพีแอ็กซ์ตร้า"),
    "egco": ("egco", "เอ็กโก"),
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
               if key in stem_key for alias in values]
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
    chosen: set[int] = set()
    matched: set[str] = set()
    for document_id, filename in documents:
        for alias in _document_aliases(filename):
            needle = normalize_search_text(alias).casefold()
            pattern = re.escape(needle)
            if re.fullmatch(r'[a-z0-9 ]+', needle):
                pattern = r'(?<![a-z0-9])' + pattern + r'(?![a-z0-9])'
            if re.search(pattern, query):
                chosen.add(int(document_id))
                matched.add(alias)
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
