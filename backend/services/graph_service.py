"""Knowledge Graph service powered by Hyper-Extract.

Two public functions:
  build_knowledge_graph(doc_id, text)  — extract & persist a KA from raw text
  search_knowledge_graph(query, doc_ids) — semantic search over stored KAs
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ka_dir(doc_id: int) -> Path:
    """Return the Knowledge Abstract directory for a given document ID."""
    base = Path(settings.HYPEREXTRACT_KA_DIR)
    return base / str(doc_id)


def _create_client():
    """Create and return (llm_client, embedder) Hyper-Extract clients."""
    from langchain_openai import ChatOpenAI
    from hyperextract.utils.client import CompatibleEmbeddings

    api_key = settings.TYPHOON_API_KEY

    llm_client = ChatOpenAI(
        model=settings.HYPEREXTRACT_LLM_MODEL,
        api_key=api_key,
        base_url=settings.HYPEREXTRACT_LLM_URL,
        temperature=0,
        max_tokens=4096,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    
    embedder = CompatibleEmbeddings(
        model=settings.HYPEREXTRACT_EMBED_MODEL,
        base_url=settings.HYPEREXTRACT_EMBED_URL,
        # Ollama does not require an API key
        api_key="ollama",
    )
    return llm_client, embedder


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_knowledge_graph(
    doc_id: int,
    text: str,
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract a Knowledge Abstract from *text* and persist it.

    Parameters
    ----------
    doc_id:   Database ID of the parent Document — used as the KA directory.
    text:     The cleaned OCR text to extract from.
    template: Hyper-Extract template name (defaults to settings.HYPEREXTRACT_TEMPLATE).

    Returns
    -------
    dict with keys: ``success``, ``entities``, ``relations``, ``ka_path``, ``error``.
    """
    if not text or not text.strip():
        return {"success": False, "error": "Empty text — nothing to extract", "entities": 0, "relations": 0}

    template = template or settings.HYPEREXTRACT_TEMPLATE
    ka_path = _ka_dir(doc_id)

    try:
        from hyperextract import Template  # type: ignore

        llm_client, embedder = _create_client()

        # Template.create(source, language, llm_client, embedder)
        # Use 'th' for Thai; falls back to 'en' if the template doesn't support Thai
        lang = getattr(settings, "HYPEREXTRACT_LANGUAGE", "th")
        ka_template = Template.create(
            template,
            language=lang,
            llm_client=llm_client,
            embedder=embedder,
        )

        # Hyper-Extract's parse() returns a KnowledgeAbstract object
        ka = ka_template.parse(text)

        # Persist KA to disk
        ka_path.mkdir(parents=True, exist_ok=True)
        ka.dump(str(ka_path))

        num_entities = len(ka.nodes) if hasattr(ka, "nodes") else 0
        num_relations = len(ka.edges) if hasattr(ka, "edges") else 0

        logger.info(
            "KA built for doc_id=%d — %d entities, %d relations -> %s",
            doc_id, num_entities, num_relations, ka_path,
        )
        return {
            "success": True,
            "entities": num_entities,
            "relations": num_relations,
            "ka_path": str(ka_path),
        }

    except ImportError:
        logger.error("hyperextract is not installed. Run: pip install hyperextract")
        return {"success": False, "error": "hyperextract package not installed", "entities": 0, "relations": 0}
    except Exception as exc:
        logger.error("KA build failed for doc_id=%d: %s", doc_id, exc)
        return {"success": False, "error": str(exc), "entities": 0, "relations": 0}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

# A graph this size fits in a prompt whole, so an unmatched query can fall back
# to returning all of it instead of reporting nothing.
_SMALL_GRAPH_LIMIT = 60

# Question scaffolding that appears in almost any Thai relationship query and so
# would match every node, drowning out the entity names that actually matter.
_GRAPH_STOPWORDS = {
    "ความสัมพันธ์", "อย่างไร", "อะไร", "ใคร", "ของ", "กับ", "คือ", "มี", "ที่",
    "ใด", "บ้าง", "เป็น", "และ", "หรือ", "ไหน", "ราย", "ใหญ่", "สุด", "ที่สุด",
    "บริษัท", "ธนาคาร", "จำกัด", "มหาชน", "กลุ่ม", "กิจการ",
    "what", "who", "which", "the", "of", "is", "are", "and", "relationship",
}


def _query_terms(query: str) -> List[str]:
    """Split a query into entity-ish terms for matching against graph elements."""
    text = str(query or "")
    if not text.strip():
        return []
    try:
        from pythainlp.tokenize import word_tokenize
        tokens = word_tokenize(text, engine="newmm", keep_whitespace=False)
    except Exception:
        tokens = re.findall(r"[A-Za-z]{2,}|\d{4}|[ก-๙]{2,}", text)

    terms, seen = [], set()
    for tok in tokens:
        t = tok.strip()
        low = t.lower()
        if len(t) < 2 or low in _GRAPH_STOPWORDS or low in seen:
            continue
        if not re.search(r"[A-Za-z0-9ก-๙]", t):
            continue
        seen.add(low)
        terms.append(t)
    return terms


def _match_score(text: str, terms: List[str]) -> int:
    """Number of query terms present in *text*, weighted by term length."""
    low = (text or "").lower()
    return sum(len(t) for t in terms if t.lower() in low)


def search_knowledge_graph(
    query: str,
    doc_ids: Optional[List[int]] = None,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search stored Knowledge Abstracts for entities/relations matching *query*.

    Parameters
    ----------
    query:   Natural language query.
    doc_ids: If provided, restrict search to these document KAs only.
             If None, search all available KAs.
    top_k:   Maximum number of results to return.

    Returns
    -------
    dict with keys: ``success``, ``summary`` (text for the agent), ``results``, ``error``.
    """
    base = Path(settings.HYPEREXTRACT_KA_DIR)

    # Determine which KA directories to search
    if doc_ids is not None:
        ka_dirs = [_ka_dir(d) for d in doc_ids if _ka_dir(d).exists()]
    else:
        if base.exists():
            ka_dirs = [p for p in base.iterdir() if p.is_dir()]
        else:
            ka_dirs = []

    if not ka_dirs:
        return {
            "success": True,
            "summary": "ยังไม่มีกราฟความรู้ที่สร้างไว้ กรุณาอัปโหลดเอกสารก่อน",
            "results": [],
        }

    try:
        # (score, summary_line, result) per graph element, ranked before returning.
        scored: List[tuple] = []
        every: List[tuple] = []

        for ka_dir in ka_dirs:
            data_file = ka_dir / "data.json"
            if not data_file.exists():
                continue
                
            try:
                import json
                with open(data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                doc_id_str = ka_dir.name
                nodes = data.get("nodes", [])
                edges = data.get("edges", [])
                
                # Match on individual query terms, not the whole query string: the
                # agent passes a full sentence ("MUFG มีความสัมพันธ์อย่างไรกับ…"),
                # which is never a substring of a node, so a whole-string test
                # reports "not found" on a graph that does contain the entity.
                terms = _query_terms(query)

                for kind, label, items in (
                    ("node", "Entity", nodes),
                    ("edge", "Relation", edges),
                ):
                    for item in items:
                        item_text = ", ".join(f"{k}: {v}" for k, v in item.items())
                        score = _match_score(item_text, terms)
                        entry = (
                            score,
                            f"[doc_id={doc_id_str}] [{label}] {item_text}",
                            {"doc_id": doc_id_str, "type": kind, "data": item},
                        )
                        every.append(entry)
                        if not terms or score > 0:
                            scored.append(entry)

            except Exception as ka_exc:
                logger.warning("Failed to read graph data for %s: %s", ka_dir, ka_exc)
                continue

        # Nothing matched by term. These graphs are small, so handing the whole
        # thing to the agent beats a false "not found" — it can judge relevance
        # itself, which it cannot do with an empty observation.
        if not scored and len(every) <= _SMALL_GRAPH_LIMIT:
            scored = every

        if not scored:
            return {
                "success": True,
                "summary": "ค้นหาในกราฟความรู้แล้ว ไม่พบข้อมูลที่ตรงกัน",
                "results": [],
            }

        scored.sort(key=lambda e: e[0], reverse=True)
        top = scored[:top_k]
        return {
            "success": True,
            "summary": "\n\n".join(line for _, line, _ in top),
            "results": [res for _, _, res in top],
        }

    except Exception as exc:
        logger.error("KA search error: %s", exc)
        return {"success": False, "summary": f"Error: {exc}", "results": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Status / Listing
# ---------------------------------------------------------------------------

def get_graph_status(doc_id: int) -> Dict[str, Any]:
    """Return build status for a document's KA."""
    ka_path = _ka_dir(doc_id)
    if not ka_path.exists():
        return {"doc_id": doc_id, "status": "not_built", "ka_path": str(ka_path)}

    files = list(ka_path.iterdir())
    return {
        "doc_id": doc_id,
        "status": "ready" if files else "empty",
        "ka_path": str(ka_path),
        "file_count": len(files),
    }


def list_all_graphs() -> List[Dict[str, Any]]:
    """List all built Knowledge Abstracts."""
    base = Path(settings.HYPEREXTRACT_KA_DIR)
    if not base.exists():
        return []

    graphs = []
    for p in sorted(base.iterdir()):
        if p.is_dir():
            files = list(p.iterdir())
            graphs.append({
                "doc_id": p.name,
                "ka_path": str(p),
                "file_count": len(files),
                "status": "ready" if files else "empty",
            })
    return graphs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_entities(ka: Any) -> int:
    """Try to count entities from a KA object safely."""
    try:
        data = ka.to_dict() if hasattr(ka, "to_dict") else {}
        entities = data.get("entities") or data.get("nodes") or []
        return len(entities)
    except Exception:
        return 0


def _count_relations(ka: Any) -> int:
    """Try to count relations from a KA object safely."""
    try:
        data = ka.to_dict() if hasattr(ka, "to_dict") else {}
        relations = data.get("relations") or data.get("edges") or []
        return len(relations)
    except Exception:
        return 0


def _hit_to_text(hit: Any) -> str:
    """Convert a search hit object to a plain text string."""
    if isinstance(hit, str):
        return hit
    if isinstance(hit, dict):
        return " | ".join(f"{k}: {v}" for k, v in hit.items())
    for attr in ("text", "content", "description", "value"):
        val = getattr(hit, attr, None)
        if val:
            return str(val)
    return str(hit)
