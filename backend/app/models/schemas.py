from pydantic import BaseModel
from datetime import datetime


class DocumentResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_size: int | None
    doc_type: str
    status: str
    page_count: int
    uploaded_at: datetime
    processed_at: datetime | None
    processing_time_ms: int | None

    class Config:
        from_attributes = True


class ExtractionResponse(BaseModel):
    id: str
    field_name: str
    field_value: str | None
    confidence: float
    source: str | None
    page_number: int
    needs_review: int

    class Config:
        from_attributes = True


class DocumentDetailResponse(BaseModel):
    document: DocumentResponse
    extractions: list[ExtractionResponse]


class SearchRequest(BaseModel):
    query: str
    doc_type: str | None = None
    limit: int = 10


class SearchResult(BaseModel):
    document_id: str
    filename: str
    doc_type: str
    snippet: str
    score: float
    extractions: list[ExtractionResponse]


class ValidationResult(BaseModel):
    field_name: str
    extracted_value: str
    is_valid: bool
    message: str


class QARequest(BaseModel):
    question: str


class QAResponse(BaseModel):
    answer: str
    confidence: float | None = None
    context_snippet: str | None = None
    document_id: str | None = None
    document_name: str | None = None
    error: str | None = None


class ProcessingStats(BaseModel):
    total_documents: int
    completed: int
    failed: int
    review_needed: int
    avg_processing_time_ms: float | None
