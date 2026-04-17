import os
import re
import logging
from sqlalchemy.orm import Session
from app.models.document import Document, ChatHistory
from app.services.rag_service import retrieve_relevant_chunks
from app.services.llm_service import answer_with_context, evaluate_chunk_relevance

logger = logging.getLogger(__name__)
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def _clean_text(text: str) -> str:
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r'[^\x20-\x7E\n]', ' ', text)
    text = re.sub(r'(?m)^.{1,2}$', '', text)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def _get_chat_history(doc_id: str | None, db: Session, limit: int = 3) -> list[dict]:
    query = db.query(ChatHistory).order_by(ChatHistory.created_at.desc())
    if doc_id:
        query = query.filter(ChatHistory.document_id == doc_id)
    history = query.limit(limit).all()
    return [{"question": h.question, "answer": h.answer} for h in reversed(history)]


def _build_context_with_metadata(chunks: list[dict]) -> str:
    """Build context string with metadata per chunk (like Sherlock)."""
    sections = []
    for i, chunk in enumerate(chunks):
        section = (
            f"\n--- Source: {chunk['filename']} | "
            f"Similarity: {chunk['similarity_score']:.3f} ---\n"
            f"{chunk['content']}\n"
        )
        sections.append(section)
    return "\n".join(sections)


def answer_question(doc_id: str, question: str, db: Session) -> dict:
    """RAG + LLM Q&A on a single document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return _error_response("Document not found", doc_id=doc_id)

    # Step 1: RAG retrieval
    chunks = retrieve_relevant_chunks(query=question, doc_ids=[doc_id], top_k=10)

    if not chunks:
        return _fallback_answer(doc, question, db)

    logger.info(f"RAG retrieved {len(chunks)} chunks for doc {doc_id}")

    # Step 2: Clean chunks
    for chunk in chunks:
        chunk["content"] = _clean_text(chunk["content"])

    # Step 3: Evaluate chunk relevance (like Sherlock's Claude evaluation)
    relevant_chunks = []
    for chunk in chunks[:8]:
        if chunk["similarity_score"] > 0.4:
            # High similarity — keep without LLM check
            relevant_chunks.append(chunk)
        else:
            # Lower similarity — ask LLM if relevant
            try:
                if evaluate_chunk_relevance(chunk["content"], question):
                    relevant_chunks.append(chunk)
                else:
                    logger.debug(f"Chunk filtered out by LLM relevance check")
            except Exception:
                relevant_chunks.append(chunk)  # Keep on error

    if not relevant_chunks:
        relevant_chunks = chunks[:3]  # Fallback

    logger.info(f"After relevance filtering: {len(relevant_chunks)} chunks kept")

    # Step 4: Build context with metadata
    context = _build_context_with_metadata(relevant_chunks[:5])

    # Step 5: Get chat history
    chat_history = _get_chat_history(doc_id, db)

    # Step 6: Generate answer with LLM
    answer = answer_with_context(question, context, chat_history)

    # Step 7: Save to chat history
    _save_chat_history(db, doc_id, question, answer, len(relevant_chunks))

    return {
        "answer": answer,
        "confidence": round(relevant_chunks[0]["similarity_score"], 4) if relevant_chunks else 0,
        "context_snippet": relevant_chunks[0]["content"][:200] if relevant_chunks else "",
        "document_id": doc_id,
        "document_name": doc.original_filename,
        "error": None,
    }


def answer_question_all_docs(question: str, db: Session) -> list[dict]:
    """RAG + LLM Q&A across ALL documents."""
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

    # Step 3: Generate answer per document
    answers = []
    for did, dchunks in doc_chunks.items():
        # Clean and build context
        for c in dchunks:
            c["content"] = _clean_text(c["content"])

        context = _build_context_with_metadata(dchunks[:4])
        answer = answer_with_context(question, context)

        if answer and "not in the context" not in answer.lower() and "cannot find" not in answer.lower():
            answers.append({
                "answer": answer,
                "confidence": round(dchunks[0]["similarity_score"], 4),
                "context_snippet": dchunks[0]["content"][:200],
                "document_id": did,
                "document_name": dchunks[0].get("filename", ""),
                "error": None,
            })

    answers.sort(key=lambda x: x["confidence"], reverse=True)

    if not answers:
        return [{"answer": "No confident answer found in any document.", "confidence": 0, "error": None}]

    # Save best to history
    _save_chat_history(db, answers[0].get("document_id"), question,
                       answers[0]["answer"], len(chunks))

    return answers[:5]


def _fallback_answer(doc: Document, question: str, db: Session) -> dict:
    """Fallback when no FAISS chunks — use full text directly."""
    if not doc.full_text:
        return _error_response("No text available. Try reprocessing.", doc.id, doc.original_filename)

    text = _clean_text(doc.full_text)
    context = text[:3000]
    answer = answer_with_context(question, context)

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
                       answer: str, chunks_used: int):
    try:
        entry = ChatHistory(
            document_id=doc_id, question=question, answer=answer,
            confidence=0, chunks_used=chunks_used,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to save chat history: {e}")
        db.rollback()
