import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentStatus, DocumentType, Extraction
from app.services.search_service import search_documents, search_from_db


CONTRACT_KEY_FIELDS = {
    "contract_number",
    "amendment_number",
    "parties",
    "date",
    "amount",
    "vendor_name",
    "buyer_name",
    "registered_number",
    "vat_number",
    "contract_term",
    "payment_terms",
    "governing_law",
    "termination_notice",
    "liability_cap",
}


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _round_metric(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _load_benchmark_data() -> dict:
    path = Path(settings.EVALUATION_BENCHMARK_FILE)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _compute_extraction_f1(db: Session, benchmark: dict) -> float | None:
    extraction_cases = benchmark.get("extraction_cases", [])
    if not extraction_cases:
        return None

    total_tp = 0
    total_fp = 0
    total_fn = 0

    for case in extraction_cases:
        doc_id = case.get("document_id")
        expected_fields = case.get("expected_fields", {})
        if not doc_id or not expected_fields:
            continue

        actual_extractions = db.query(Extraction).filter(Extraction.document_id == doc_id).all()
        actual_map: dict[str, list[str]] = defaultdict(list)
        for ext in actual_extractions:
            actual_map[ext.field_name].append(_normalize_text(ext.field_value))

        expected_map: dict[str, list[str]] = defaultdict(list)
        for field_name, field_value in expected_fields.items():
            if isinstance(field_value, list):
                expected_map[field_name].extend(_normalize_text(v) for v in field_value)
            else:
                expected_map[field_name].append(_normalize_text(field_value))

        for field_name, expected_values in expected_map.items():
            actual_values = actual_map.get(field_name, []).copy()
            for expected_value in expected_values:
                if expected_value in actual_values:
                    total_tp += 1
                    actual_values.remove(expected_value)
                else:
                    total_fn += 1
            total_fp += len(actual_values)

        expected_field_names = set(expected_map.keys())
        for field_name, actual_values in actual_map.items():
            if field_name not in expected_field_names:
                total_fp += len(actual_values)

    precision = _safe_div(total_tp, total_tp + total_fp)
    recall = _safe_div(total_tp, total_tp + total_fn)
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return _round_metric(2 * precision * recall / (precision + recall))


def _search_rankings(db: Session, query: str, doc_type: str | None, limit: int) -> list[dict]:
    # Evaluation should be based on the durable benchmark state in SQLite.
    # The in-memory keyword index can become stale after documents are deleted.
    return search_from_db(query, db, doc_type, limit)


def _compute_search_metrics(db: Session, benchmark: dict) -> tuple[float | None, float | None]:
    search_cases = benchmark.get("search_cases", [])
    if not search_cases:
        return None, None

    precision_scores: list[float] = []
    reciprocal_ranks: list[float] = []

    for case in search_cases:
        query = case.get("query")
        relevant_ids = set(case.get("relevant_document_ids", []))
        if not query or not relevant_ids:
            continue

        results = _search_rankings(db, query, case.get("doc_type"), 5)
        top_ids = [result["document_id"] for result in results[:5]]
        denominator = max(1, min(5, len(top_ids)))

        hits = sum(1 for doc_id in top_ids if doc_id in relevant_ids)
        precision_scores.append(hits / denominator)

        rr = 0.0
        for rank, doc_id in enumerate(top_ids, 1):
            if doc_id in relevant_ids:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

    precision_at_5 = _safe_div(sum(precision_scores), len(precision_scores))
    mrr = _safe_div(sum(reciprocal_ranks), len(reciprocal_ranks))
    return _round_metric(precision_at_5), _round_metric(mrr)


def _compute_throughput(db: Session) -> float | None:
    completed_docs = db.query(Document).filter(
        Document.status.in_([DocumentStatus.COMPLETED, DocumentStatus.REVIEW_NEEDED]),
        Document.processing_time_ms.isnot(None),
    ).all()
    processing_times = [doc.processing_time_ms for doc in completed_docs if doc.processing_time_ms]
    if not processing_times:
        return None
    avg_processing_time_ms = sum(processing_times) / len(processing_times)
    if avg_processing_time_ms <= 0:
        return None
    return _round_metric(3600000 / avg_processing_time_ms, 2)


def _compute_review_rate(db: Session) -> float | None:
    extractions = db.query(Extraction).all()
    if not extractions:
        return None
    needs_review = sum(1 for extraction in extractions if extraction.needs_review)
    return _round_metric(needs_review / len(extractions))


def _compute_contract_field_coverage(db: Session) -> float | None:
    contract_docs = db.query(Document).filter(
        Document.status.in_([DocumentStatus.COMPLETED, DocumentStatus.REVIEW_NEEDED]),
        Document.doc_type == DocumentType.CONTRACT,
    ).all()
    if not contract_docs:
        return None

    scores: list[float] = []
    for doc in contract_docs:
        fields = {
            row.field_name
            for row in db.query(Extraction.field_name).filter(Extraction.document_id == doc.id).all()
            if row.field_name in CONTRACT_KEY_FIELDS
        }
        scores.append(len(fields) / len(CONTRACT_KEY_FIELDS))
    return _round_metric(sum(scores) / len(scores))


def _count_contract_documents(db: Session) -> int:
    return db.query(Document).filter(Document.doc_type == DocumentType.CONTRACT).count()


def _metric(
    key: str,
    label: str,
    value: float | str | None,
    description: str,
    unit: str | None = None,
    category: str = "implemented",
) -> dict:
    if isinstance(value, (float, int)):
        display_value = f"{value}{unit or ''}"
        status = "measured"
    elif value is None:
        display_value = "Not measured"
        status = "pending"
    else:
        display_value = str(value)
        status = "pending"

    return {
        "key": key,
        "label": label,
        "value": value,
        "display_value": display_value,
        "description": description,
        "unit": unit,
        "status": status,
        "category": category,
    }


def get_evaluation_metrics(db: Session) -> dict:
    benchmark = _load_benchmark_data()

    extraction_f1 = _compute_extraction_f1(db, benchmark)
    precision_at_5, mrr = _compute_search_metrics(db, benchmark)
    throughput = _compute_throughput(db)
    review_rate = _compute_review_rate(db)
    contract_count = _count_contract_documents(db)
    contract_field_coverage = _compute_contract_field_coverage(db)

    metrics = [
        _metric(
            "contract_corpus_size",
            "Contract Corpus Size",
            contract_count,
            "Number of documents currently classified as contracts or imported as sample contracts.",
        ),
        _metric(
            "contract_field_coverage",
            "Contract Field Coverage",
            contract_field_coverage,
            "Average coverage of thesis-relevant contract fields such as parties, term, payment, law, notice, and liability.",
        ),
        _metric(
            "field_extraction_f1",
            "Field Extraction F1",
            extraction_f1,
            "Measures precision/recall balance for key-value extraction across benchmark documents.",
        ),
        _metric(
            "search_precision_at_5",
            "Search Precision@5",
            precision_at_5,
            "Tracks how often the top five search results contain relevant benchmark documents.",
        ),
        _metric(
            "search_mrr",
            "Search MRR",
            mrr,
            "Measures how early the first relevant document appears in ranked search results.",
        ),
        _metric(
            "qa_answer_accuracy",
            "QA Answer Accuracy",
            None,
            "Reserved for benchmarked question-answering evaluation against labeled answers.",
            category="planned",
        ),
        _metric(
            "throughput",
            "Throughput",
            throughput,
            "Documents processed per hour, estimated from recorded processing times.",
            unit=" docs/hr",
        ),
        _metric(
            "review_rate",
            "Review Rate",
            review_rate,
            "Fraction of extracted fields flagged for manual review due to low confidence or validation checks.",
        ),
    ]

    return {
        "benchmark_available": bool(benchmark),
        "metrics": metrics,
    }
