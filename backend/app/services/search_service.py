import re
import logging
from sqlalchemy.orm import Session
from app.models.document import Document, Extraction, DocumentStatus

logger = logging.getLogger(__name__)

# In-memory search index (replaces Elasticsearch for quick setup)
_search_index: list[dict] = []


def index_document(doc_id: str, text: str, doc_type: str, filename: str, extractions: list[dict]):
    """Add a document to the search index."""
    global _search_index
    _search_index = [entry for entry in _search_index if entry["document_id"] != doc_id]
    _search_index.append({
        "document_id": doc_id,
        "text": text.lower(),
        "filename_lower": filename.lower(),
        "doc_type": doc_type,
        "filename": filename,
        "extractions": extractions,
    })


def reset_search_index():
    """Clear the in-memory keyword index before a full corpus rebuild."""
    global _search_index
    _search_index = []


def search_documents(query: str, doc_type: str | None = None, limit: int = 10) -> list[dict]:
    """Simple keyword search over indexed documents."""
    query_lower = query.lower()
    query_terms = _tokenize(query)
    results = []

    for entry in _search_index:
        if doc_type and entry["doc_type"] != doc_type:
            continue

        score = _score_document(
            query_lower=query_lower,
            query_terms=query_terms,
            filename=entry["filename_lower"],
            full_text=entry["text"],
            extractions=entry["extractions"],
        )
        if score > 0:
            snippet = _get_snippet(entry["text"], query_terms)
            results.append({
                "document_id": entry["document_id"],
                "filename": entry["filename"],
                "doc_type": entry["doc_type"],
                "snippet": snippet,
                "score": round(score, 3),
                "extractions": entry["extractions"],
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def search_from_db(query: str, db: Session, doc_type: str | None = None, limit: int = 10) -> list[dict]:
    """Fallback: search directly from database."""
    q = db.query(Document).filter(
        Document.status.in_([DocumentStatus.COMPLETED, DocumentStatus.REVIEW_NEEDED])
    )
    if doc_type:
        q = q.filter(Document.doc_type == doc_type)

    documents = q.all()
    if not documents:
        return []

    query_lower = query.lower()
    query_terms = _tokenize(query)
    doc_ids = [doc.id for doc in documents]
    extractions_by_doc: dict[str, list[Extraction]] = {doc_id: [] for doc_id in doc_ids}
    matching_extractions = db.query(Extraction).filter(Extraction.document_id.in_(doc_ids)).all()
    for ext in matching_extractions:
        extractions_by_doc.setdefault(ext.document_id, []).append(ext)

    results = []

    for doc in documents:
        doc_extractions = extractions_by_doc.get(doc.id, [])
        extractions_payload = [
            {"field_name": e.field_name, "field_value": e.field_value,
             "confidence": e.confidence, "source": e.source}
            for e in doc_extractions
        ]
        match_score = _score_document(
            query_lower=query_lower,
            query_terms=query_terms,
            filename=doc.original_filename.lower(),
            full_text=(doc.full_text or "").lower(),
            extractions=extractions_payload,
        )

        if match_score > 0:
            matched_extractions = _filter_matching_extractions(doc_extractions, query_terms, query_lower)
            results.append({
                "document_id": doc.id,
                "filename": doc.original_filename,
                "doc_type": doc.doc_type.value if doc.doc_type else "other",
                "snippet": _build_snippet(doc.original_filename, doc.full_text or "", matched_extractions, query_terms),
                "score": round(match_score, 3),
                "extractions": [
                    {"field_name": e.field_name, "field_value": e.field_value,
                     "confidence": e.confidence, "source": e.source}
                    for e in matched_extractions
                ],
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def _get_snippet(text: str, terms: list[str], window: int = 100) -> str:
    """Extract a text snippet around the first matching term."""
    for term in terms:
        idx = text.find(term)
        if idx >= 0:
            start = max(0, idx - window // 2)
            end = min(len(text), idx + len(term) + window // 2)
            snippet = text[start:end]
            return f"...{snippet}..." if start > 0 else f"{snippet}..."
    return text[:200] + "..." if len(text) > 200 else text


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9]+", text.lower()) if len(token) > 1]


def _score_document(
    query_lower: str,
    query_terms: list[str],
    filename: str,
    full_text: str,
    extractions: list[dict],
) -> float:
    if not query_terms:
        return 0.0

    score = 0.0

    if query_lower in filename:
        score += 8.0
    if query_lower and query_lower in full_text:
        score += 5.0

    filename_tokens = set(_tokenize(filename))
    text_tokens = set(_tokenize(full_text))

    for term in query_terms:
        if term in filename_tokens:
            score += 3.0
        elif term in filename:
            score += 2.0

        if term in text_tokens:
            score += 1.5
        elif term in full_text:
            score += 0.75

        for ext in extractions:
            field_name = str(ext.get("field_name", "")).lower()
            field_value = str(ext.get("field_value", "")).lower()
            if term in field_value:
                score += 2.5
                break
            if term in field_name:
                score += 0.8
                break

    coverage = sum(
        1 for term in query_terms
        if term in filename or term in full_text or any(term in str(ext.get("field_value", "")).lower() for ext in extractions)
    )
    score += coverage / len(query_terms)
    return score


def _filter_matching_extractions(extractions: list[Extraction], query_terms: list[str], query_lower: str) -> list[Extraction]:
    matched = []
    for ext in extractions:
        field_name = (ext.field_name or "").lower()
        field_value = (ext.field_value or "").lower()
        if query_lower in field_name or query_lower in field_value:
            matched.append(ext)
            continue
        if any(term in field_name or term in field_value for term in query_terms):
            matched.append(ext)
    return matched


def _build_snippet(filename: str, full_text: str, matched_extractions: list[Extraction], query_terms: list[str]) -> str:
    if matched_extractions:
        first = matched_extractions[0]
        return f"{first.field_name}: {first.field_value}"
    if any(term in filename.lower() for term in query_terms):
        return f"Matched filename: {filename}"
    return _get_snippet(full_text.lower(), query_terms)
