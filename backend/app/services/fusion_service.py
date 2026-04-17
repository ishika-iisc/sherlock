import logging

logger = logging.getLogger(__name__)


def fuse_results(ocr_result: dict, vlm_result: dict, confidence_threshold: float = 0.7) -> dict:
    """
    Fuse OCR and VLM extraction results using confidence-weighted merging.

    Strategy:
    - Use VLM for document classification and layout understanding
    - Use OCR for raw text extraction
    - Merge word-level results, preferring higher-confidence source
    """
    fused = {
        "full_text": ocr_result.get("full_text", ""),
        "doc_type": vlm_result.get("doc_type", "other"),
        "doc_type_confidence": vlm_result.get("confidence", 0.0),
        "source": "fused",
        "words": [],
        "metadata": {
            "ocr_word_count": len(ocr_result.get("words", [])),
            "vlm_available": vlm_result.get("has_layout", False),
        },
    }

    # Merge word-level data from OCR
    for word in ocr_result.get("words", []):
        fused["words"].append({
            "text": word["text"],
            "confidence": word["confidence"],
            "bbox": word.get("bbox"),
            "source": "ocr",
        })

    # If VLM provided better text, use it
    if vlm_result.get("has_layout") and not ocr_result.get("full_text", "").strip():
        fused["source"] = "vlm"
        logger.info("Using VLM as primary source (OCR text was empty)")

    # Flag low-confidence words for review
    low_conf_count = sum(1 for w in fused["words"] if w["confidence"] < confidence_threshold)
    fused["metadata"]["low_confidence_words"] = low_conf_count
    fused["metadata"]["needs_review"] = low_conf_count > len(fused["words"]) * 0.3

    return fused
