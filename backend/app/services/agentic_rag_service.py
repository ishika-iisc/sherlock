import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus, Extraction
from app.services.llm_service import answer_with_context
from app.services.qa_service import FIELD_ALIASES
from app.services.rag_service import retrieve_relevant_chunks

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 5200
MIN_EVIDENCE_SCORE = 0.18
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "did", "do", "does",
    "for", "from", "give", "has", "have", "how", "i", "in", "is", "it", "list", "me",
    "of", "on", "or", "please", "show", "tell", "that", "the", "this", "to", "was", "what",
    "when", "where", "which", "who", "with", "would", "all", "any",
}


@dataclass
class QueryPlan:
    intent: str
    field_name: str | None
    subqueries: list[str]
    explanation: str


def answer_agentic_rag(
    question: str,
    db: Session,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    max_evidence: int = 6,
) -> dict:
    """Plan, retrieve, grade evidence, and answer with citations."""
    started = time.perf_counter()
    steps = []
    doc_ids = _normalize_document_ids(document_id, document_ids)
    max_evidence = max(2, min(max_evidence, 10))

    try:
        plan = _plan_question(question)
        steps.append(_step("plan", "complete", plan.explanation))

        if plan.intent == "field_lookup" and len(doc_ids) <= 1:
            structured = _answer_from_structured_fields(question, plan.field_name, db, doc_ids[0] if doc_ids else None)
            if structured:
                steps.append(_step("structured_field_lookup", "complete", "Answered from extracted fields."))
                structured.update({
                    "intent": plan.intent,
                    "steps": steps,
                    "latency_ms": _elapsed_ms(started),
                })
                return structured
            steps.append(_step("structured_field_lookup", "skipped", "No matching extracted field value was available."))

        raw_evidence = _retrieve_evidence(plan, db, doc_ids)
        steps.append(_step("retrieve", "complete", f"Retrieved {len(raw_evidence)} candidate evidence chunks."))

        graded = _grade_evidence(raw_evidence, question, plan)
        evidence = graded[:max_evidence]
        steps.append(_step("grade", "complete", f"Selected {len(evidence)} evidence chunks after scoring."))

        if not evidence or evidence[0]["score"] < MIN_EVIDENCE_SCORE:
            answer = "I do not have enough reliable evidence in the indexed documents to answer that."
            confidence = evidence[0]["score"] if evidence else 0.0
            return {
                "answer": answer,
                "intent": plan.intent,
                "confidence": round(confidence, 4),
                "evidence": evidence,
                "steps": steps + [_step("answer", "limited", "Evidence was below the confidence threshold.")],
                "latency_ms": _elapsed_ms(started),
                "error": None,
            }

        context = _build_context(evidence)
        answer = _generate_grounded_answer(question, context, plan)
        confidence = _confidence_from_evidence(evidence)
        steps.append(_step("answer", "complete", "Generated answer from selected evidence only."))

        return {
            "answer": answer,
            "intent": plan.intent,
            "confidence": confidence,
            "evidence": evidence,
            "steps": steps,
            "latency_ms": _elapsed_ms(started),
            "error": None,
        }
    except Exception as exc:
        logger.exception("Agentic RAG failed")
        return {
            "answer": "Agentic RAG could not complete the request.",
            "intent": "error",
            "confidence": 0.0,
            "evidence": [],
            "steps": steps + [_step("error", "failed", str(exc))],
            "latency_ms": _elapsed_ms(started),
            "error": str(exc),
        }


def _plan_question(question: str) -> QueryPlan:
    normalized = question.lower()
    field_name = _detect_field(normalized)
    tokens = set(_tokens(question))

    if field_name:
        intent = "field_lookup"
        subqueries = [question, field_name.replace("_", " ")]
        explanation = f"Detected a structured field lookup for '{field_name}'."
    elif tokens & {"compare", "difference", "differences", "changed", "changes", "versus", "vs"}:
        intent = "comparison"
        subqueries = [question, f"compare differences changes {question}", f"amendment original revised clause {question}"]
        explanation = "Detected a comparison question; retrieval will look for changed or related clauses."
    elif tokens & {"risk", "risky", "review", "missing", "expired", "expiry", "unusual"}:
        intent = "risk_review"
        subqueries = [question, f"risk obligation termination payment liability date {question}"]
        explanation = "Detected a risk-review question; retrieval will prioritize obligations and exceptions."
    elif normalized.startswith(("summarize", "summary", "explain")) or "overview" in normalized:
        intent = "summary"
        subqueries = [question, "parties dates amount obligations termination payment"]
        explanation = "Detected a summary question; retrieval will gather broad document facts."
    else:
        intent = "grounded_qa"
        subqueries = [question]
        explanation = "Using grounded document Q&A with evidence grading."

    return QueryPlan(intent=intent, field_name=field_name, subqueries=_dedupe_strings(subqueries), explanation=explanation)


def _retrieve_evidence(plan: QueryPlan, db: Session, doc_ids: list[str]) -> list[dict]:
    candidates = []
    seen = set()

    for query in plan.subqueries:
        chunks = retrieve_relevant_chunks(query=query, doc_ids=doc_ids or None, top_k=12)
        for chunk in chunks:
            key = (chunk.get("doc_id"), chunk.get("chunk_index"), chunk.get("content", "")[:120])
            if key in seen:
                continue
            seen.add(key)
            candidates.append({**chunk, "source": "vector", "matched_query": query})

    if candidates:
        return candidates

    return _fallback_text_evidence(db, doc_ids, " ".join(plan.subqueries))


def _fallback_text_evidence(db: Session, doc_ids: list[str], query: str) -> list[dict]:
    q = db.query(Document).filter(Document.status.in_([DocumentStatus.COMPLETED, DocumentStatus.REVIEW_NEEDED]))
    if doc_ids:
        q = q.filter(Document.id.in_(doc_ids))

    terms = _tokens(query)
    candidates = []
    for doc in q.limit(25).all():
        text = doc.full_text or ""
        if not text:
            continue
        snippet = _best_snippet(text, terms)
        if snippet:
            candidates.append({
                "doc_id": doc.id,
                "filename": doc.original_filename,
                "doc_type": doc.doc_type.value if doc.doc_type else "other",
                "chunk_index": 0,
                "content": snippet,
                "similarity_score": 0.0,
                "source": "text_fallback",
                "matched_query": query,
            })
    return candidates


def _grade_evidence(candidates: list[dict], question: str, plan: QueryPlan) -> list[dict]:
    question_terms = _tokens(question)
    graded = []
    for index, item in enumerate(candidates):
        content = _clean(item.get("content", ""))
        if not content:
            continue
        lowered = content.lower()
        coverage = _coverage(question_terms, lowered)
        vector_score = float(item.get("similarity_score") or 0.0)
        intent_bonus = _intent_bonus(lowered, plan)
        matched_terms = [term for term in question_terms if term in lowered][:8]
        score = min(1.0, (vector_score * 0.65) + (coverage * 0.30) + intent_bonus)
        graded.append({
            "document_id": item.get("doc_id"),
            "document_name": item.get("filename"),
            "snippet": content[:900],
            "score": round(score, 4),
            "source": item.get("source", "vector"),
            "matched_query": item.get("matched_query"),
            "matched_terms": matched_terms,
            "clause_type": _classify_clause(lowered),
            "evidence_reason": _evidence_reason(item, coverage, intent_bonus, matched_terms),
            "rank": index + 1,
        })

    graded.sort(key=lambda item: item["score"], reverse=True)
    return _dedupe_evidence(graded)


def _answer_from_structured_fields(question: str, field_name: str | None, db: Session, doc_id: str | None) -> dict | None:
    if not field_name:
        return None

    q = db.query(Extraction, Document).join(Document, Document.id == Extraction.document_id)
    q = q.filter(Extraction.field_name == field_name)
    if doc_id:
        q = q.filter(Extraction.document_id == doc_id)

    rows = q.order_by(Extraction.confidence.desc()).limit(8).all()
    if not rows:
        return None

    label = field_name.replace("_", " ")
    evidence = []
    values = []
    seen = set()
    for extraction, doc in rows:
        value = (extraction.field_value or "").strip()
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        values.append(value)
        evidence.append({
            "document_id": doc.id,
            "document_name": doc.original_filename,
            "snippet": f"{label}: {value}",
            "score": round(extraction.confidence or 0.0, 4),
            "source": "extraction",
            "matched_query": question,
            "rank": len(evidence) + 1,
        })

    if not values:
        return None

    answer = f"The {label} is {values[0]}." if len(values) == 1 else f"The {label} values found are: {'; '.join(values)}."
    return {
        "answer": answer,
        "confidence": round(max(item["score"] for item in evidence), 4),
        "evidence": evidence,
        "error": None,
    }


def _generate_grounded_answer(question: str, context: str, plan: QueryPlan) -> str:
    prefix = (
        f"Question intent: {plan.intent}.\n"
        "Use only the evidence below. If the evidence is incomplete, say what is missing. "
        "Prefer concise, business-readable language and do not invent values.\n\n"
    )
    return answer_with_context(question, prefix + context, chat_history=None)


def _build_context(evidence: list[dict]) -> str:
    sections = []
    used_chars = 0
    for idx, item in enumerate(evidence, 1):
        snippet = item["snippet"]
        if sections and used_chars + len(snippet) > MAX_CONTEXT_CHARS:
            continue
        sections.append(
            f"[Evidence {idx} | {item.get('document_name')} | score {item['score']:.3f}]\n{snippet}"
        )
        used_chars += len(snippet)
    return "\n\n".join(sections)


def _confidence_from_evidence(evidence: list[dict]) -> float:
    if not evidence:
        return 0.0
    top = evidence[0]["score"]
    support = min(len([item for item in evidence if item["score"] >= MIN_EVIDENCE_SCORE]) / 4, 1.0)
    return round(min(1.0, (top * 0.75) + (support * 0.25)), 4)


def _intent_bonus(text: str, plan: QueryPlan) -> float:
    if plan.intent == "comparison":
        return 0.12 if any(term in text for term in ("amend", "change", "revised", "replace", "supersede")) else 0.0
    if plan.intent == "risk_review":
        return 0.12 if any(term in text for term in ("terminate", "liability", "penalty", "expiry", "breach", "obligation")) else 0.0
    if plan.intent == "summary":
        return 0.08 if any(term in text for term in ("between", "effective", "term", "payment", "party")) else 0.0
    if plan.intent == "field_lookup" and plan.field_name:
        return 0.14 if plan.field_name.replace("_", " ") in text else 0.0
    return 0.0


def _classify_clause(text: str) -> str:
    clause_map = {
        "payment": ("payment", "invoice", "fees", "charges", "payable"),
        "termination": ("terminate", "termination", "notice period", "prior written notice"),
        "liability": ("liability", "indemnity", "damages", "cap", "limitation"),
        "term": ("term", "commencement", "expiry", "expiration", "duration"),
        "law": ("governing law", "jurisdiction", "laws of"),
        "parties": ("between", "party", "parties", "supplier", "customer", "client"),
        "amendment": ("amendment", "change", "revised", "supersede"),
    }
    for clause_type, markers in clause_map.items():
        if any(marker in text for marker in markers):
            return clause_type
    return "general"


def _evidence_reason(item: dict, coverage: float, intent_bonus: float, matched_terms: list[str]) -> str:
    source = item.get("source", "vector")
    parts = [f"{source} evidence"]
    if matched_terms:
        parts.append(f"matched {len(matched_terms)} question term(s)")
    if coverage >= 0.5:
        parts.append("high lexical coverage")
    elif coverage > 0:
        parts.append("partial lexical coverage")
    if intent_bonus > 0:
        parts.append("contract-intent signal")
    return "; ".join(parts)


def _detect_field(normalized_question: str) -> str | None:
    matches: list[tuple[int, str]] = []
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized_question:
                matches.append((len(alias), field_name))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _tokens(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    ]


def _coverage(terms: list[str], lowered_text: str) -> float:
    if not terms:
        return 0.0
    matches = sum(1 for term in terms if term in lowered_text)
    return matches / len(terms)


def _best_snippet(text: str, terms: list[str], window: int = 1200) -> str:
    lowered = text.lower()
    best_index = -1
    for term in terms:
        idx = lowered.find(term)
        if idx >= 0:
            best_index = idx
            break
    if best_index < 0:
        return _clean(text[:window]) if text else ""
    start = max(0, best_index - window // 3)
    end = min(len(text), start + window)
    return _clean(text[start:end])


def _clean(text: str) -> str:
    text = re.sub(r"[^\x20-\x7E\n]", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _dedupe_evidence(items: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for item in items:
        fingerprint = (item.get("document_id"), item.get("snippet", "")[:180].lower())
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        item["rank"] = len(output) + 1
        output.append(item)
    return output


def _dedupe_strings(items: list[str]) -> list[str]:
    output = []
    seen = set()
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            output.append(item)
            seen.add(key)
    return output


def _normalize_document_ids(document_id: str | None, document_ids: list[str] | None) -> list[str]:
    ids = []
    if document_id:
        ids.append(document_id)
    ids.extend(document_ids or [])
    output = []
    seen = set()
    for item in ids:
        if item and item not in seen:
            output.append(item)
            seen.add(item)
    return output


def _step(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
