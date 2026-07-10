"""Knowledge Graph service powered by Hyper-Extract.

Two public functions:
  build_knowledge_graph(doc_id, text)  — extract & persist a KA from raw text
  search_knowledge_graph(query, doc_ids) — semantic search over stored KAs
"""

from __future__ import annotations

import logging
import os
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
        all_results: List[Dict[str, Any]] = []
        summary_lines = []

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
                
                # We can filter locally by simple keyword match, or just return all if it's small.
                # Since graphs per doc are usually compact, returning all for the LLM is often best.
                # But let's do a basic keyword filter if query is provided, or return all if query is broad.
                q = query.lower()
                
                # Format nodes
                for node in nodes:
                    node_text = ", ".join(f"{k}: {v}" for k, v in node.items())
                    if not q or q in node_text.lower():
                        summary_lines.append(f"[doc_id={doc_id_str}] [Entity] {node_text}")
                        all_results.append({"doc_id": doc_id_str, "type": "node", "data": node})
                
                # Format edges
                for edge in edges:
                    edge_text = ", ".join(f"{k}: {v}" for k, v in edge.items())
                    if not q or q in edge_text.lower():
                        summary_lines.append(f"[doc_id={doc_id_str}] [Relation] {edge_text}")
                        all_results.append({"doc_id": doc_id_str, "type": "edge", "data": edge})

            except Exception as ka_exc:
                logger.warning("Failed to read graph data for %s: %s", ka_dir, ka_exc)
                continue

        if not all_results:
            return {
                "success": True,
                "summary": "ค้นหาในกราฟความรู้แล้ว ไม่พบข้อมูลที่ตรงกัน",
                "results": [],
            }

        return {
            "success": True,
            "summary": "\n\n".join(summary_lines),
            "results": all_results,
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
