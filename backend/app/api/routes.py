import shutil
import uuid
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.config import settings
from app.models.document import Document, Extraction, DocumentStatus
from app.models.schemas import (
    DocumentResponse, DocumentDetailResponse, ExtractionResponse,
    SearchRequest, SearchResult, ValidationResult, ProcessingStats,
    QARequest, QAResponse,
)
from app.services.search_service import search_documents, search_from_db
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(doc_id: str, db: Session = Depends(get_db)):
    """Get document details with extractions."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    extractions = db.query(Extraction).filter(Extraction.document_id == doc_id).all()
    return {"document": doc, "extractions": extractions}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: Session = Depends(get_db)):
    """Delete a document and its extractions."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    file_path = Path(doc.file_path)
    if file_path.exists():
        file_path.unlink()
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
