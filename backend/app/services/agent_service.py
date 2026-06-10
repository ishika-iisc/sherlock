import logging
import re
import time
from typing import Literal

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus
from app.services.qa_service import answer_question, answer_question_all_docs
from app.services.search_service import search_documents, search_from_db

logger = logging.getLogger(__name__)

AgentRoute = Literal["search", "single_document", "multi_document", "global_qa"]

SEARCH_WORDS = {
    "find", "search", "show", "list", "documents", "files", "uploaded", "where",
}
COMPARE_WORDS = {
    "compare", "difference", "differences", "across", "between", "versus", "vs",
}


def ask_agent(
    question: str,
    db: Session,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    mode: str = "auto",
    limit: int = 5,
) -> dict:
    """Route a user question to the fastest safe backend capability."""
    start = time.perf_counter()
    selected_ids = _normalize_document_ids(document_id, document_ids)
    route, reasoning = _choose_route(question, selected_ids, mode)
    limit = max(1, min(limit, 10))

    try:
        if route == "search":
            result = _run_search(question, db, limit)
        elif route == "single_document":
            result = _run_single_document(question, db, selected_ids[0])
        elif route == "multi_document":
            result = _run_multi_document(question, db, selected_ids[:limit])
        else:
            result = _run_global_qa(question, db, limit)
    except Exception as exc:
        logger.exception("Agent route %s failed", route)
        result = {
            "answer": "I could not complete the request. Please try again or narrow the question.",
            "confidence": 0.0,
            "citations": [],
            "error": str(exc),
        }

    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "answer": result["answer"],
        "route": route,
        "confidence": result.get("confidence"),
        "citations": result.get("citations", []),
        "latency_ms": latency_ms,
        "reasoning": reasoning,
        "error": result.get("error"),
    }


def _normalize_document_ids(document_id: str | None, document_ids: list[str] | None) -> list[str]:
    ids = []
    if document_id:
        ids.append(document_id)
    ids.extend(document_ids or [])
    normalized = []
    seen = set()
    for item in ids:
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _choose_route(question: str, document_ids: list[str], mode: str) -> tuple[AgentRoute, str]:
    if mode == "single_document" and not document_ids:
        return "global_qa", "Single-document mode was requested without a document id; using global Q&A."
    if mode == "multi_document" and not document_ids:
        return "global_qa", "Multi-document mode was requested without document ids; using global Q&A."
    if mode in {"search", "single_document", "multi_document", "global_qa"}:
        return mode, f"Requested explicit mode '{mode}'."

    terms = set(re.findall(r"[a-zA-Z0-9]+", question.lower()))
    if len(document_ids) == 1:
        return "single_document", "One document id was supplied, so answer against that document."
    if len(document_ids) > 1:
        return "multi_document", "Multiple document ids were supplied, so answer per document."
    if terms & SEARCH_WORDS and not _looks_like_question_answering(question):
        return "search", "The question looks like document discovery/search."
    if terms & COMPARE_WORDS:
        return "global_qa", "The question asks across documents or for comparison."
    return "global_qa", "No document id supplied, so use global RAG over indexed documents."


def _looks_like_question_answering(question: str) -> bool:
    normalized = question.strip().lower()
    qa_starts = ("what ", "who ", "when ", "where ", "why ", "how ", "which ", "summarize", "explain")
    return normalized.endswith("?") or normalized.startswith(qa_starts)


def _run_search(question: str, db: Session, limit: int) -> dict:
    results = search_documents(question, limit=limit)
    if not results:
        results = search_from_db(question, db, limit=limit)

    if not results:
        return {
            "answer": "I did not find matching documents.",
            "confidence": 0.0,
            "citations": [],
            "error": None,
        }

    lines = ["I found these matching documents:"]
    citations = []
    for index, item in enumerate(results, 1):
        lines.append(f"{index}. {item['filename']} ({item['doc_type']})")
        citations.append(_citation_from_search(item))

    return {
        "answer": "\n".join(lines),
        "confidence": results[0].get("score", 0.0),
        "citations": citations,
        "error": None,
    }


def _run_single_document(question: str, db: Session, doc_id: str) -> dict:
    doc = _get_ready_document(db, doc_id)
    if not doc:
        return {
            "answer": "Document was not found or is not ready for Q&A.",
            "confidence": 0.0,
            "citations": [],
            "error": "document_not_ready",
        }

    answer = answer_question(doc.id, question, db)
    return {
        "answer": answer["answer"],
        "confidence": answer.get("confidence") or 0.0,
        "citations": [_citation_from_qa(answer)],
        "error": answer.get("error"),
    }


def _run_multi_document(question: str, db: Session, doc_ids: list[str]) -> dict:
    if not doc_ids:
        return _run_global_qa(question, db, limit=5)

    answers = []
    citations = []
    confidences = []
    for doc_id in doc_ids:
        doc = _get_ready_document(db, doc_id)
        if not doc:
            continue
        answer = answer_question(doc.id, question, db)
        if answer.get("answer"):
            answers.append(f"{doc.original_filename}: {answer['answer']}")
            citations.append(_citation_from_qa(answer))
            confidences.append(answer.get("confidence") or 0.0)

    if not answers:
        return {
            "answer": "None of the selected documents are ready for Q&A.",
            "confidence": 0.0,
            "citations": [],
            "error": "documents_not_ready",
        }

    return {
        "answer": "\n\n".join(answers),
        "confidence": max(confidences) if confidences else 0.0,
        "citations": citations,
        "error": None,
    }


def _run_global_qa(question: str, db: Session, limit: int) -> dict:
    answers = answer_question_all_docs(question, db)
    if not answers:
        return {
            "answer": "No answer found.",
            "confidence": 0.0,
            "citations": [],
            "error": None,
        }

    ready_answers = answers[:limit]
    if len(ready_answers) == 1:
        answer_text = ready_answers[0]["answer"]
    else:
        answer_text = "\n\n".join(
            f"{item.get('document_name') or item.get('document_id')}: {item['answer']}"
            for item in ready_answers
        )

    confidences = [item.get("confidence") or 0.0 for item in ready_answers]
    return {
        "answer": answer_text,
        "confidence": max(confidences) if confidences else 0.0,
        "citations": [_citation_from_qa(item) for item in ready_answers],
        "error": ready_answers[0].get("error"),
    }


def _get_ready_document(db: Session, doc_id: str) -> Document | None:
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return None
    if doc.status not in (DocumentStatus.COMPLETED, DocumentStatus.REVIEW_NEEDED):
        return None
    return doc


def _citation_from_qa(item: dict) -> dict:
    return {
        "document_id": item.get("document_id"),
        "document_name": item.get("document_name"),
        "snippet": item.get("context_snippet"),
        "confidence": item.get("confidence"),
    }


def _citation_from_search(item: dict) -> dict:
    return {
        "document_id": item.get("document_id"),
        "document_name": item.get("filename"),
        "snippet": item.get("snippet"),
        "confidence": item.get("score"),
    }
