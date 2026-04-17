import logging
from sqlalchemy.orm import Session
from app.models.document import Document, Extraction, DocumentStatus

logger = logging.getLogger(__name__)

# In-memory search index (replaces Elasticsearch for quick setup)
_search_index: list[dict] = []


def index_document(doc_id: str, text: str, doc_type: str, filename: str, extractions: list[dict]):
    """Add a document to the search index."""
    _search_index.append({
        "document_id": doc_id,
        "text": text.lower(),
        "doc_type": doc_type,
        "filename": filename,
        "extractions": extractions,
    })


def search_documents(query: str, doc_type: str | None = None, limit: int = 10) -> list[dict]:
    """Simple keyword search over indexed documents."""
    query_lower = query.lower()
    query_terms = query_lower.split()
    results = []

    for entry in _search_index:
        if doc_type and entry["doc_type"] != doc_type:
            continue

        text = entry["text"]
        # Score: fraction of query terms found in text
        matches = sum(1 for term in query_terms if term in text)
        if matches == 0:
            # Also check extraction values
            for ext in entry["extractions"]:
                val = str(ext.get("field_value", "")).lower()
                matches += sum(1 for term in query_terms if term in val)

        if matches > 0:
            score = matches / len(query_terms)
            snippet = _get_snippet(text, query_terms)
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
    q = db.query(Document).filter(Document.status == DocumentStatus.COMPLETED)
    if doc_type:
        q = q.filter(Document.doc_type == doc_type)

    documents = q.all()
    query_lower = query.lower()
    results = []

    for doc in documents:
        extractions = db.query(Extraction).filter(Extraction.document_id == doc.id).all()
        match_score = 0
        for ext in extractions:
            if ext.field_value and query_lower in ext.field_value.lower():
                match_score += 1

        if match_score > 0 or query_lower in doc.filename.lower():
            results.append({
                "document_id": doc.id,
                "filename": doc.original_filename,
                "doc_type": doc.doc_type.value if doc.doc_type else "other",
                "snippet": f"Found in {match_score} fields",
                "score": match_score,
                "extractions": [
                    {"field_name": e.field_name, "field_value": e.field_value,
                     "confidence": e.confidence, "source": e.source}
                    for e in extractions
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
