import shutil
import uuid
import logging
import mimetypes
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.config import settings
from app.models.document import Document, Extraction, DocumentStatus, DocumentType, ProcessingLog
from app.models.schemas import (
    DocumentResponse, DocumentDetailResponse, ExtractionResponse,
    SearchRequest, SearchResult, ValidationResult, ProcessingStats,
    QARequest, QAResponse, AgentRequest, AgentResponse,
    AgenticRAGRequest, AgenticRAGResponse, EvaluationMetricsResponse,
)
from app.services.search_service import search_documents, search_from_db
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


def _process_many_in_background(doc_ids: list[str], rebuild_indexes: bool = False):
    from app.services.document_processor import process_document

    db_bg = SessionLocal()
    try:
        if rebuild_indexes:
            from app.services.rag_service import reset_index
            from app.services.search_service import reset_search_index

            reset_search_index()
            reset_index()

        for doc_id in doc_ids:
            try:
                process_document(doc_id, db_bg)
            except Exception:
                logger.exception("Batch processing failed for %s", doc_id)
    finally:
        db_bg.close()


@router.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a document for processing."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in settings.SUPPORTED_FORMATS:
        raise HTTPException(400, f"Unsupported format: {suffix}. Supported: {settings.SUPPORTED_FORMATS}")

    doc_id = str(uuid.uuid4())
    filename = f"{doc_id}{suffix}"
    file_path = settings.DOCUMENTS_DIR / filename

    settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = file_path.stat().st_size
    if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        file_path.unlink()
        raise HTTPException(400, f"File too large. Max: {settings.MAX_FILE_SIZE_MB}MB")

    doc = Document(
        id=doc_id,
        filename=filename,
        original_filename=file.filename,
        file_path=str(file_path),
        file_size=file_size,
        mime_type=file.content_type,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    def _process_in_background(doc_id: str):
        from app.services.document_processor import process_document
        db_bg = SessionLocal()
        try:
            process_document(doc_id, db_bg)
        finally:
            db_bg.close()

    background_tasks.add_task(_process_in_background, doc_id)
    return doc


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    status: str | None = None,
    doc_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List all documents with optional filters."""
    q = db.query(Document)
    if status:
        q = q.filter(Document.status == status)
    if doc_type:
        q = q.filter(Document.doc_type == doc_type)
    return q.order_by(Document.uploaded_at.desc()).offset(skip).limit(limit).all()


@router.post("/documents/import-samples")
async def import_sample_contracts(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Import configured local sample contracts for thesis/demo evaluation."""
    source_dir = Path(settings.SAMPLE_CONTRACTS_DIR).expanduser()
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(404, f"Sample contracts folder not found: {source_dir}")

    settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    imported_docs: list[Document] = []
    skipped: list[dict] = []

    for source_path in sorted(source_dir.iterdir()):
        if not source_path.is_file():
            continue
        suffix = source_path.suffix.lower()
        if suffix not in settings.SUPPORTED_FORMATS:
            skipped.append({"filename": source_path.name, "reason": "unsupported_format"})
            continue

        file_size = source_path.stat().st_size
        if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            skipped.append({"filename": source_path.name, "reason": "file_too_large"})
            continue

        existing = db.query(Document).filter(
            Document.original_filename == source_path.name,
            Document.file_size == file_size,
        ).first()
        if existing:
            skipped.append({"filename": source_path.name, "reason": "already_imported"})
            continue

        doc_id = str(uuid.uuid4())
        filename = f"{doc_id}{suffix}"
        file_path = settings.DOCUMENTS_DIR / filename
        shutil.copyfile(source_path, file_path)

        mime_type, _ = mimetypes.guess_type(str(source_path))
        doc = Document(
            id=doc_id,
            filename=filename,
            original_filename=source_path.name,
            file_path=str(file_path),
            file_size=file_size,
            mime_type=mime_type or "application/pdf",
            doc_type=DocumentType.CONTRACT,
        )
        db.add(doc)
        imported_docs.append(doc)

    db.commit()
    imported_payload = [
        {"id": doc.id, "filename": doc.original_filename}
        for doc in imported_docs
    ]
    imported_ids = [doc.id for doc in imported_docs]
    if imported_ids:
        background_tasks.add_task(_process_many_in_background, imported_ids, False)

    return {
        "message": f"Queued {len(imported_ids)} sample contract(s) for processing.",
        "source_dir": str(source_dir),
        "imported_count": len(imported_ids),
        "skipped_count": len(skipped),
        "imported": imported_payload,
        "skipped": skipped,
    }


@router.post("/documents/reprocess")
async def reprocess_documents(
    background_tasks: BackgroundTasks,
    contract_only: bool = False,
    db: Session = Depends(get_db),
):
    """Re-process the current corpus and rebuild keyword/semantic indexes."""
    q = db.query(Document)
    if contract_only:
        q = q.filter(Document.doc_type == DocumentType.CONTRACT)
    docs = q.order_by(Document.uploaded_at.asc()).all()
    if not docs:
        raise HTTPException(404, "No documents found to reprocess")

    doc_ids = [doc.id for doc in docs]
    db.query(Extraction).filter(Extraction.document_id.in_(doc_ids)).delete(synchronize_session=False)
    db.query(ProcessingLog).filter(ProcessingLog.document_id.in_(doc_ids)).delete(synchronize_session=False)
    for doc in docs:
        doc.status = DocumentStatus.UPLOADED
        doc.processed_at = None
        doc.processing_time_ms = None
    db.commit()

    background_tasks.add_task(_process_many_in_background, doc_ids, True)
    return {
        "message": f"Queued {len(doc_ids)} document(s) for reprocessing.",
        "queued_count": len(doc_ids),
        "contract_only": contract_only,
        "rebuild_indexes": True,
    }


@router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(doc_id: str, db: Session = Depends(get_db)):
    """Get document details with extractions."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    extractions = db.query(Extraction).filter(Extraction.document_id == doc_id).all()
    processing_logs = db.query(ProcessingLog).filter(
        ProcessingLog.document_id == doc_id
    ).order_by(ProcessingLog.created_at.asc()).all()
    return {"document": doc, "extractions": extractions, "processing_logs": processing_logs}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: Session = Depends(get_db)):
    """Delete a document and its extractions."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    file_path = Path(doc.file_path)
    if file_path.exists():
        file_path.unlink()
    db.query(ProcessingLog).filter(ProcessingLog.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()
    return {"message": "Document deleted"}


@router.post("/documents/{doc_id}/reprocess")
async def reprocess_document(
    doc_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Re-process a document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    # Clear old extractions
    db.query(Extraction).filter(Extraction.document_id == doc_id).delete()
    db.query(ProcessingLog).filter(ProcessingLog.document_id == doc_id).delete()
    db.commit()
    def _reprocess_in_background(doc_id: str):
        from app.services.document_processor import process_document
        db_bg = SessionLocal()
        try:
            process_document(doc_id, db_bg)
        finally:
            db_bg.close()

    background_tasks.add_task(_reprocess_in_background, doc_id)
    return {"message": "Reprocessing started"}


@router.get("/documents/{doc_id}/validate", response_model=list[ValidationResult])
async def validate_document(doc_id: str, db: Session = Depends(get_db)):
    """Validate extracted data against business rules."""
    extractions = db.query(Extraction).filter(Extraction.document_id == doc_id).all()
    if not extractions:
        raise HTTPException(404, "No extractions found")
    from app.services.validation_service import validate_extractions
    entities = [{"field_name": e.field_name, "field_value": e.field_value} for e in extractions]
    return validate_extractions(entities)


@router.post("/documents/{doc_id}/ask", response_model=QAResponse)
async def ask_question(doc_id: str, request: QARequest, db: Session = Depends(get_db)):
    """Ask a question about a specific document using RAG."""
    from app.services.qa_service import answer_question
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status not in (DocumentStatus.COMPLETED, DocumentStatus.REVIEW_NEEDED):
        raise HTTPException(400, "Document is still processing")
    return answer_question(doc_id, request.question, db)


@router.post("/ask", response_model=list[QAResponse])
async def ask_all_documents(request: QARequest, db: Session = Depends(get_db)):
    """Ask a question across all documents using RAG."""
    from app.services.qa_service import answer_question_all_docs
    return answer_question_all_docs(request.question, db)


@router.post("/agent/ask", response_model=AgentResponse)
async def agent_ask(request: AgentRequest, db: Session = Depends(get_db)):
    """Ask through the backend agent router."""
    from app.services.agent_service import ask_agent
    return ask_agent(
        question=request.question,
        db=db,
        document_id=request.document_id,
        document_ids=request.document_ids,
        mode=request.mode,
        limit=request.limit,
    )


@router.post("/agentic-rag/ask", response_model=AgenticRAGResponse)
async def agentic_rag_ask(request: AgenticRAGRequest, db: Session = Depends(get_db)):
    """Ask through the agentic RAG workflow."""
    from app.services.agentic_rag_service import answer_agentic_rag
    return answer_agentic_rag(
        question=request.question,
        db=db,
        document_id=request.document_id,
        document_ids=request.document_ids,
        max_evidence=request.max_evidence,
    )


@router.post("/search", response_model=list[SearchResult])
async def search(request: SearchRequest, db: Session = Depends(get_db)):
    """Search documents by keyword or natural language query."""
    results = search_documents(request.query, request.doc_type, request.limit)
    if not results:
        results = search_from_db(request.query, db, request.doc_type, request.limit)
    return results


@router.get("/stats", response_model=ProcessingStats)
async def get_stats(db: Session = Depends(get_db)):
    """Get processing statistics."""
    total = db.query(func.count(Document.id)).scalar()
    completed = db.query(func.count(Document.id)).filter(Document.status == DocumentStatus.COMPLETED).scalar()
    failed = db.query(func.count(Document.id)).filter(Document.status == DocumentStatus.FAILED).scalar()
    review = db.query(func.count(Document.id)).filter(Document.status == DocumentStatus.REVIEW_NEEDED).scalar()
    avg_time = db.query(func.avg(Document.processing_time_ms)).filter(
        Document.processing_time_ms.isnot(None)
    ).scalar()
    return ProcessingStats(
        total_documents=total or 0, completed=completed or 0,
        failed=failed or 0, review_needed=review or 0,
        avg_processing_time_ms=round(avg_time, 2) if avg_time else None,
    )


@router.get("/evaluation/metrics", response_model=EvaluationMetricsResponse)
async def evaluation_metrics(db: Session = Depends(get_db)):
    """Compute evaluation metrics from benchmark data and recorded processing results."""
    from app.services.evaluation_service import get_evaluation_metrics
    return get_evaluation_metrics(db)
