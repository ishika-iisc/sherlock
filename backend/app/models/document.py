import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Integer, Text, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW_NEEDED = "review_needed"


class DocumentType(str, enum.Enum):
    INVOICE = "invoice"
    CONTRACT = "contract"
    FORM = "form"
    REPORT = "report"
    OTHER = "other"


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String)
    page_count = Column(Integer, default=1)
    doc_type = Column(SQLEnum(DocumentType), default=DocumentType.OTHER)
    status = Column(SQLEnum(DocumentStatus), default=DocumentStatus.UPLOADED)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    full_text = Column(Text, nullable=True)

    extractions = relationship("Extraction", back_populates="document", cascade="all, delete-orphan")


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    confidence = Column(Float, default=0.0)
    chunks_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Extraction(Base):
    __tablename__ = "extractions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    field_name = Column(String, nullable=False)
    field_value = Column(Text)
    confidence = Column(Float, default=0.0)
    source = Column(String)  # "ocr", "vlm", "fused"
    page_number = Column(Integer, default=1)
    bbox = Column(JSON, nullable=True)  # bounding box [x1, y1, x2, y2]
    needs_review = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="extractions")
