from pydantic import BaseModel, Field
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


class ProcessingLogResponse(BaseModel):
    id: str
    step: str
    level: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentDetailResponse(BaseModel):
    document: DocumentResponse
    extractions: list[ExtractionResponse]
    processing_logs: list[ProcessingLogResponse]


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


class AgentRequest(BaseModel):
    question: str
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    mode: str = "auto"
    limit: int = 5


class AgentCitation(BaseModel):
    document_id: str | None = None
    document_name: str | None = None
    snippet: str | None = None
    confidence: float | None = None


class AgentResponse(BaseModel):
    answer: str
    route: str
    confidence: float | None = None
    citations: list[AgentCitation]
    latency_ms: int
    reasoning: str
    error: str | None = None


class AgenticRAGRequest(BaseModel):
    question: str
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    max_evidence: int = 6


class AgenticRAGEvidence(BaseModel):
    document_id: str | None = None
    document_name: str | None = None
    snippet: str
    score: float
    source: str
    matched_query: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    clause_type: str | None = None
    evidence_reason: str | None = None
    rank: int


class AgenticRAGStep(BaseModel):
    name: str
    status: str
    detail: str


class AgenticRAGResponse(BaseModel):
    answer: str
    intent: str
    confidence: float
    evidence: list[AgenticRAGEvidence]
    steps: list[AgenticRAGStep]
    latency_ms: int
    error: str | None = None


class ProcessingStats(BaseModel):
    total_documents: int
    completed: int
    failed: int
    review_needed: int
    avg_processing_time_ms: float | None


class EvaluationMetricResponse(BaseModel):
    key: str
    label: str
    value: float | str | None
    display_value: str
    description: str
    unit: str | None = None
    status: str
    category: str


class EvaluationMetricsResponse(BaseModel):
    benchmark_available: bool
    metrics: list[EvaluationMetricResponse]
