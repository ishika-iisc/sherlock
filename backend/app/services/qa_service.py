import os
import re
import logging
from sqlalchemy.orm import Session
from app.models.document import Document, ChatHistory, Extraction
from app.services.rag_service import retrieve_relevant_chunks
from app.services.llm_service import answer_with_context

logger = logging.getLogger(__name__)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

MAX_CONTEXT_CHARS = 4200
MAX_SINGLE_DOC_CHUNKS = 5
MAX_ALL_DOCS = 3
MAX_ALL_DOC_CHUNKS = 3

FIELD_ALIASES = {
    "invoice_number": ("invoice number", "invoice no", "invoice #", "inv number", "inv no"),
    "contract_number": ("contract number", "contract no", "contract #", "contract id", "contract reference"),
    "amendment_number": ("amendment number", "amendment no", "amendment #"),
    "date": ("date", "effective date", "signed date", "agreement date", "contract date"),
    "amount": ("amount", "total amount", "total", "value", "price", "cost", "balance due"),
    "vendor_name": ("vendor", "supplier", "seller", "vendor name", "supplier name"),
    "buyer_name": ("buyer", "customer", "client", "buyer name", "customer name"),
    "parties": ("parties", "party", "between whom", "who are the parties"),
    "email": ("email", "email address", "contact email"),
    "phone": ("phone", "telephone", "mobile", "contact number"),
    "po_number": ("po number", "purchase order", "purchase order number", "po no"),
    "vat_number": ("vat", "vat number", "vat registration"),
    "registered_number": ("registered number", "registration number", "company number"),
    "contract_term": ("term", "contract term", "initial term", "duration", "expiry", "expiration"),
    "payment_terms": ("payment terms", "payment term", "invoice payment", "net days", "payable"),
    "governing_law": ("governing law", "jurisdiction", "laws of"),
    "termination_notice": ("termination notice", "notice period", "prior written notice"),
    "liability_cap": ("liability cap", "liability limit", "limited liability", "shall not exceed"),
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "did", "do", "does",
    "for", "from", "give", "has", "have", "how", "i", "in", "is", "it", "list", "me",
    "of", "on", "or", "please", "show", "tell", "that", "the", "this", "to", "was", "what",
    "when", "where", "which", "who", "with", "would",
}


def _clean_text(text: str) -> str:
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r'[^\x20-\x7E\n]', ' ', text)
    text = re.sub(r'(?m)^.{1,2}$', '', text)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _tokenize_query(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [token for token in tokens if len(token) > 2 and token not in STOP_WORDS]


def _get_chat_history(doc_id: str | None, db: Session, limit: int = 3) -> list[dict]:
    query = db.query(ChatHistory).order_by(ChatHistory.created_at.desc())
    if doc_id:
        query = query.filter(ChatHistory.document_id == doc_id)
    history = query.limit(limit).all()
    return [{"question": h.question, "answer": h.answer} for h in reversed(history)]


def _get_cached_answer(doc_id: str | None, question: str, db: Session) -> dict | None:
    """Return a previous exact answer instead of re-running retrieval and LLM."""
    normalized = _normalize_question(question)
    query = db.query(ChatHistory).order_by(ChatHistory.created_at.desc())
    if doc_id:
        query = query.filter(ChatHistory.document_id == doc_id)

    for item in query.limit(10).all():
        if _normalize_question(item.question) == normalized and item.answer:
            return {
                "answer": item.answer,
                "confidence": item.confidence or 0.0,
                "context_snippet": "Returned from recent chat history.",
                "document_id": doc_id,
                "document_name": None,
                "error": None,
            }
    return None


def _detect_requested_field(question: str) -> str | None:
    normalized = _normalize_question(question)
    matches: list[tuple[int, str]] = []
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                matches.append((len(alias), field_name))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _answer_from_extractions(doc_id: str, question: str, db: Session) -> dict | None:
    """Fast path for questions already answered by structured extraction."""
    field_name = _detect_requested_field(question)
    if not field_name:
        return None

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return None

    rows = (
        db.query(Extraction)
        .filter(Extraction.document_id == doc_id, Extraction.field_name == field_name)
        .order_by(Extraction.confidence.desc())
        .all()
    )
    values = []
    seen = set()
    for row in rows:
        value = (row.field_value or "").strip()
        if not value:
            continue
        value_key = value.lower()
        if value_key in seen:
            continue
        seen.add(value_key)
        values.append((value, row.confidence or 0.0))

    if not values:
        return None

    label = field_name.replace("_", " ")
    if len(values) == 1:
        answer = f"The {label} is {values[0][0]}."
    else:
        joined = "; ".join(value for value, _ in values[:5])
        answer = f"The {label} values found are: {joined}."

    return {
        "answer": answer,
        "confidence": round(max(score for _, score in values), 4),
        "context_snippet": f"{label}: {values[0][0]}",
        "document_id": doc_id,
        "document_name": doc.original_filename,
        "error": None,
    }


def _answer_all_docs_from_extractions(question: str, db: Session) -> list[dict] | None:
    field_name = _detect_requested_field(question)
    if not field_name:
        return None

    rows = (
        db.query(Extraction, Document)
        .join(Document, Document.id == Extraction.document_id)
        .filter(Extraction.field_name == field_name)
        .order_by(Extraction.confidence.desc())
        .limit(20)
        .all()
    )
    if not rows:
        return None

    answers = []
    seen_docs = set()
    label = field_name.replace("_", " ")
    for extraction, doc in rows:
        if doc.id in seen_docs:
            continue
        value = (extraction.field_value or "").strip()
        if not value:
            continue
        seen_docs.add(doc.id)
        answers.append({
            "answer": f"The {label} is {value}.",
            "confidence": round(extraction.confidence or 0.0, 4),
            "context_snippet": f"{label}: {value}",
            "document_id": doc.id,
            "document_name": doc.original_filename,
            "error": None,
        })
    return answers or None


def _rank_chunks(chunks: list[dict], question: str) -> list[dict]:
    """Hybrid rerank: vector similarity plus cheap lexical coverage."""
    terms = _tokenize_query(question)
    if not terms:
        return chunks

    ranked = []
    for chunk in chunks:
        content = _clean_text(chunk.get("content", ""))
        lowered = content.lower()
        matches = sum(1 for term in terms if term in lowered)
        coverage = matches / len(terms)
        proximity_bonus = 0.0
        if len(terms) > 1 and any(" ".join(terms[i:i + 2]) in lowered for i in range(len(terms) - 1)):
            proximity_bonus = 0.08
        vector_score = float(chunk.get("similarity_score", 0.0))
        hybrid_score = vector_score + (coverage * 0.35) + proximity_bonus
        ranked.append({**chunk, "content": content, "hybrid_score": hybrid_score})

    ranked.sort(key=lambda c: c["hybrid_score"], reverse=True)
    return ranked


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for chunk in chunks:
        content = chunk.get("content", "")
        fingerprint = re.sub(r"\s+", " ", content[:500].lower()).strip()
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(chunk)
    return deduped


def _select_context_chunks(chunks: list[dict], question: str, limit: int) -> list[dict]:
    ranked = _rank_chunks(chunks, question)
    ranked = _dedupe_chunks(ranked)
    selected = []
    used_chars = 0
    for chunk in ranked:
        content_len = len(chunk.get("content", ""))
        if selected and used_chars + content_len > MAX_CONTEXT_CHARS:
            continue
        selected.append(chunk)
        used_chars += content_len
        if len(selected) >= limit:
            break
    return selected or ranked[:limit]


def _build_context_with_metadata(chunks: list[dict]) -> str:
    """Build context string with metadata per chunk (like Sherlock)."""
    sections = []
    for i, chunk in enumerate(chunks):
        section = (
            f"\n--- Source: {chunk['filename']} | "
            f"Similarity: {chunk['similarity_score']:.3f} | "
            f"Rank: {chunk.get('hybrid_score', chunk['similarity_score']):.3f} ---\n"
            f"{chunk['content']}\n"
        )
        sections.append(section)
    return "\n".join(sections)


def answer_question(doc_id: str, question: str, db: Session) -> dict:
    """RAG + LLM Q&A on a single document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return _error_response("Document not found", doc_id=doc_id)

    cached = _get_cached_answer(doc_id, question, db)
    if cached:
        cached["document_name"] = doc.original_filename
        return cached

    extraction_answer = _answer_from_extractions(doc_id, question, db)
    if extraction_answer:
        _save_chat_history(
            db, doc_id, question, extraction_answer["answer"],
            chunks_used=0, confidence=extraction_answer["confidence"]
        )
        return extraction_answer

    # Step 1: RAG retrieval
    chunks = retrieve_relevant_chunks(query=question, doc_ids=[doc_id], top_k=10)

    if not chunks:
        return _fallback_answer(doc, question, db)

    logger.info(f"RAG retrieved {len(chunks)} chunks for doc {doc_id}")

    # Step 2: Cheap hybrid rerank and dedupe. This avoids multiple LLM calls before answer generation.
    relevant_chunks = _select_context_chunks(chunks, question, MAX_SINGLE_DOC_CHUNKS)
    logger.info("After hybrid rerank: %s chunks kept", len(relevant_chunks))

    # Step 3: Build compact context with metadata
    context = _build_context_with_metadata(relevant_chunks)

    # Step 4: Get chat history
    chat_history = _get_chat_history(doc_id, db)

    # Step 5: Generate answer with LLM
    answer = answer_with_context(question, context, chat_history)

    # Step 6: Save to chat history
    confidence = round(relevant_chunks[0]["similarity_score"], 4) if relevant_chunks else 0
    _save_chat_history(db, doc_id, question, answer, len(relevant_chunks), confidence=confidence)

    return {
        "answer": answer,
        "confidence": confidence,
        "context_snippet": relevant_chunks[0]["content"][:200] if relevant_chunks else "",
        "document_id": doc_id,
        "document_name": doc.original_filename,
        "error": None,
    }


def answer_question_all_docs(question: str, db: Session) -> list[dict]:
    """RAG + LLM Q&A across ALL documents."""
    extraction_answers = _answer_all_docs_from_extractions(question, db)
    if extraction_answers:
        best = extraction_answers[0]
        _save_chat_history(
            db, best.get("document_id"), question, best["answer"],
            chunks_used=0, confidence=best.get("confidence") or 0
        )
        return extraction_answers[:5]

    # Step 1: Global retrieval
    chunks = retrieve_relevant_chunks(query=question, doc_ids=None, top_k=15)

    if not chunks:
        return [{"answer": "No documents indexed yet.", "confidence": 0, "error": "no_docs"}]

    # Step 2: Group by document
    doc_chunks: dict[str, list[dict]] = {}
    for chunk in chunks:
        did = chunk["doc_id"]
        if did not in doc_chunks:
            doc_chunks[did] = []
        doc_chunks[did].append(chunk)

    # Step 3: Generate answer per top document only. This caps slow local LLM calls.
    answers = []
    ordered_docs = sorted(
        doc_chunks.items(),
        key=lambda item: max(chunk.get("similarity_score", 0.0) for chunk in item[1]),
        reverse=True,
    )
    for did, dchunks in ordered_docs[:MAX_ALL_DOCS]:
        selected = _select_context_chunks(dchunks, question, MAX_ALL_DOC_CHUNKS)

        context = _build_context_with_metadata(selected)
        answer = answer_with_context(question, context)

        if answer and "not in the context" not in answer.lower() and "cannot find" not in answer.lower():
            answers.append({
                "answer": answer,
                "confidence": round(selected[0]["similarity_score"], 4),
                "context_snippet": selected[0]["content"][:200],
                "document_id": did,
                "document_name": selected[0].get("filename", ""),
                "error": None,
            })

    answers.sort(key=lambda x: x["confidence"], reverse=True)

    if not answers:
        return [{"answer": "No confident answer found in any document.", "confidence": 0, "error": None}]

    # Save best to history
    _save_chat_history(db, answers[0].get("document_id"), question,
                       answers[0]["answer"], len(chunks), confidence=answers[0]["confidence"])

    return answers[:5]


def _fallback_answer(doc: Document, question: str, db: Session) -> dict:
    """Fallback when no FAISS chunks — use full text directly."""
    if not doc.full_text:
        return _error_response("No text available. Try reprocessing.", doc.id, doc.original_filename)

    text = _clean_text(doc.full_text)
    context = text[:3000]
    answer = answer_with_context(question, context)
    _save_chat_history(db, doc.id, question, answer, 0, confidence=0.5)

    return {
        "answer": answer,
        "confidence": 0.5,
        "context_snippet": context[:200],
        "document_id": doc.id,
        "document_name": doc.original_filename,
        "error": None,
    }


def _error_response(msg: str, doc_id: str = None, doc_name: str = None) -> dict:
    return {"answer": msg, "confidence": 0, "context_snippet": "",
            "document_id": doc_id, "document_name": doc_name, "error": msg}


def _save_chat_history(db: Session, doc_id: str | None, question: str,
                       answer: str, chunks_used: int, confidence: float = 0.0):
    try:
        entry = ChatHistory(
            document_id=doc_id, question=question, answer=answer,
            confidence=confidence, chunks_used=chunks_used,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to save chat history: {e}")
        db.rollback()
