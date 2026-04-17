import time
import logging
from pathlib import Path
from PIL import Image
from PyPDF2 import PdfReader
from sqlalchemy.orm import Session

from app.models.document import Document, Extraction, DocumentStatus, DocumentType
from app.services.entity_extraction import extract_entities, normalize_entities
from app.services.validation_service import validate_extractions
from app.services.search_service import index_document
from app.core.config import settings

logger = logging.getLogger(__name__)


def process_document(doc_id: str, db: Session):
    """Full processing pipeline."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        logger.error(f"Document {doc_id} not found")
        return

    doc.status = DocumentStatus.PROCESSING
    db.commit()
    start_time = time.time()

    try:
        file_path = Path(doc.file_path)

        # Step 1: Text extraction (fast path vs slow path)
        pdf_text = _extract_pdf_text(file_path)
        if pdf_text and len(pdf_text.strip()) > 100:
            all_text, page_count, page_classifications = _process_text_pdf(doc, pdf_text, file_path)
        else:
            all_text, page_count, page_classifications = _process_scanned(doc, file_path)

        doc.page_count = page_count

        # Step 2: Table extraction
        table_text = _extract_tables(file_path)

        # Step 3: Combine all text
        full_text = "\n".join(all_text)
        if table_text:
            full_text += "\n\n" + table_text
        doc.full_text = full_text

        # Step 4: Entity extraction — regex (fast) + LLM (catches what regex misses)
        entities = extract_entities(full_text)
        entities = normalize_entities(entities)
        regex_fields = {e["field_name"] for e in entities}

        try:
            from app.services.llm_service import extract_entities_llm
            llm_entities = extract_entities_llm(full_text)
            for le in llm_entities:
                if le["field_name"] not in regex_fields and le.get("field_value"):
                    entities.append(le)
                    logger.info(f"LLM found extra field: {le['field_name']}={le['field_value']}")
        except Exception as e:
            logger.warning(f"LLM entity extraction skipped: {e}")

        # Step 5: Detect multi-document PDFs
        doc_boundaries = _detect_document_boundaries(page_classifications)
        if len(doc_boundaries) > 1:
            logger.info(f"Multi-document PDF detected: {len(doc_boundaries)} sub-documents")

        for entity in entities:
            extraction = Extraction(
                document_id=doc_id,
                field_name=entity["field_name"],
                field_value=entity["field_value"],
                confidence=entity["confidence"],
                source=entity.get("source", "fused"),
                page_number=1,
                needs_review=1 if entity["confidence"] < settings.CONFIDENCE_THRESHOLD else 0,
            )
            db.add(extraction)

        # Step 6: Validate
        validations = validate_extractions(entities)
        for v in validations:
            if not v["is_valid"]:
                ext = db.query(Extraction).filter(
                    Extraction.document_id == doc_id,
                    Extraction.field_name == v["field_name"],
                ).first()
                if ext:
                    ext.needs_review = 1

        # Step 7: Index for keyword search
        index_document(
            doc_id=doc_id, text=full_text,
            doc_type=doc.doc_type.value if doc.doc_type else "other",
            filename=doc.original_filename,
            extractions=[{"field_name": e["field_name"], "field_value": e["field_value"]} for e in entities],
        )

        # Step 8: RAG indexing
        from app.services.rag_service import index_document_chunks
        num_chunks = index_document_chunks(
            doc_id=doc_id, text=full_text,
            filename=doc.original_filename,
            doc_type=doc.doc_type.value if doc.doc_type else "other",
        )
        logger.info(f"RAG indexed {num_chunks} chunks for doc {doc_id}")

        # Finalize
        elapsed_ms = int((time.time() - start_time) * 1000)
        doc.status = DocumentStatus.COMPLETED
        doc.processing_time_ms = elapsed_ms
        doc.processed_at = __import__("datetime").datetime.utcnow()

        review_count = db.query(Extraction).filter(
            Extraction.document_id == doc_id, Extraction.needs_review == 1
        ).count()
        if review_count > 0:
            doc.status = DocumentStatus.REVIEW_NEEDED

        db.commit()
        logger.info(f"Document {doc_id} processed in {elapsed_ms}ms, "
                     f"{len(entities)} entities, {page_count} pages")

    except Exception as e:
        logger.error(f"Processing failed for {doc_id}: {e}")
        doc.status = DocumentStatus.FAILED
        db.commit()
        raise


# --- Text extraction ---

def _extract_pdf_text(file_path: Path) -> str | None:
    if file_path.suffix.lower() != ".pdf":
        return None
    try:
        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return None


def _process_text_pdf(doc, pdf_text: str, file_path: Path) -> tuple[list[str], int, list[dict]]:
    """Fast path: digital PDF. Classify ALL pages with VLM."""
    reader = PdfReader(str(file_path))
    page_count = len(reader.pages)

    # Per-page classification (Sherlock-style)
    page_classifications = []
    try:
        from pdf2image import convert_from_path
        from app.services.vlm_service import vlm_service
        images = convert_from_path(str(file_path), dpi=150)
        page_classifications = vlm_service.classify_all_pages(images)
        if page_classifications:
            # Use page 1's classification as the document type
            doc.doc_type = _map_doc_type(page_classifications[0]["doc_type"])
    except Exception as e:
        logger.warning(f"Per-page VLM classification failed: {e}")
        doc.doc_type = DocumentType.OTHER

    all_text = [page.extract_text() or "" for page in reader.pages]
    logger.info(f"Text PDF: {page_count} pages, {len(pdf_text)} chars")
    return all_text, page_count, page_classifications


def _process_scanned(doc, file_path: Path) -> tuple[list[str], int, list[dict]]:
    """Slow path: scanned document. OCR + VLM on every page."""
    images = _load_images(file_path)

    from app.services.ocr_service import ocr_service
    from app.services.vlm_service import vlm_service
    from app.services.fusion_service import fuse_results

    # Per-page classification
    page_classifications = vlm_service.classify_all_pages(images)
    if page_classifications:
        doc.doc_type = _map_doc_type(page_classifications[0]["doc_type"])

    all_text = []
    for page_num, image in enumerate(images, 1):
        ocr_result = ocr_service.extract(image)
        vlm_result = vlm_service.extract_layout_features(image)
        fused = fuse_results(ocr_result, vlm_result, settings.CONFIDENCE_THRESHOLD)
        all_text.append(fused["full_text"])

    return all_text, len(images), page_classifications


# --- Table extraction ---

def _extract_tables(file_path: Path) -> str:
    """Extract tables and convert to text for indexing."""
    try:
        from app.services.table_service import extract_tables_from_pdf, extract_tables_from_image, tables_to_text

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            tables = extract_tables_from_pdf(str(file_path))
        elif suffix in (".png", ".jpg", ".jpeg", ".tiff"):
            image = Image.open(file_path)
            tables = extract_tables_from_image(image)
        else:
            return ""

        if tables:
            logger.info(f"Extracted {len(tables)} tables from {file_path.name}")
            return tables_to_text(tables)
    except Exception as e:
        logger.warning(f"Table extraction skipped: {e}")
    return ""


# --- Multi-document detection ---

def _detect_document_boundaries(page_classifications: list[dict]) -> list[list[int]]:
    """Detect sub-document boundaries in a multi-document PDF.
    Returns list of page groups, e.g. [[1,2,3], [4,5]] for 2 sub-documents."""
    if not page_classifications:
        return [[1]]

    boundaries = []
    current_group = []

    for pc in page_classifications:
        page = pc["page"]
        role = pc["role"]

        if role == "first_page" and current_group:
            boundaries.append(current_group)
            current_group = [page]
        elif role == "single_page":
            if current_group:
                boundaries.append(current_group)
            boundaries.append([page])
            current_group = []
        else:
            current_group.append(page)

    if current_group:
        boundaries.append(current_group)

    return boundaries if boundaries else [[1]]


# --- Helpers ---

def _load_images(file_path: Path) -> list[Image.Image]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pdf2image import convert_from_path
            return convert_from_path(str(file_path), dpi=150)
        except Exception:
            logger.warning("pdf2image failed")
            return [Image.new("RGB", (100, 100), "white")]
    elif suffix in (".png", ".jpg", ".jpeg", ".tiff"):
        return [Image.open(file_path)]
    else:
        raise ValueError(f"Unsupported format: {suffix}")


def _map_doc_type(predicted: str) -> DocumentType:
    mapping = {
        "invoice": DocumentType.INVOICE,
        "contract": DocumentType.CONTRACT,
        "form": DocumentType.FORM,
        "report": DocumentType.REPORT,
    }
    return mapping.get(predicted, DocumentType.OTHER)
