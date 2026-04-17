import logging
from PIL import Image

logger = logging.getLogger(__name__)

# Page roles for multi-document detection
PAGE_ROLES = ["first_page", "mid_page", "last_page", "single_page"]


class VLMService:
    """Vision-Language Model service using LayoutLMv3 for document understanding."""

    def __init__(self):
        self._processor = None
        self._model = None
        self._loaded = False

    def _load_model(self):
        if self._loaded:
            return
        try:
            from transformers import LayoutLMv3Processor, LayoutLMv3ForSequenceClassification
            self._processor = LayoutLMv3Processor.from_pretrained(
                "microsoft/layoutlmv3-base", apply_ocr=True
            )
            self._model = LayoutLMv3ForSequenceClassification.from_pretrained(
                "microsoft/layoutlmv3-base", num_labels=5
            )
            self._model.eval()
            self._loaded = True
            logger.info("LayoutLMv3 model loaded")
        except Exception as e:
            logger.error(f"Failed to load VLM model: {e}")
            self._loaded = False

    def classify_document(self, image: Image.Image) -> dict:
        """Classify document type with calibrated confidence from softmax."""
        self._load_model()
        if not self._loaded:
            return {"doc_type": "other", "confidence": 0.0, "all_scores": {}, "error": "Model not loaded"}

        try:
            import torch
            encoding = self._processor(image, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model(**encoding)
            probs = torch.softmax(outputs.logits, dim=-1)
            pred_idx = probs.argmax(-1).item()
            confidence = probs[0][pred_idx].item()

            labels = ["invoice", "contract", "form", "report", "other"]
            all_scores = {labels[i]: round(probs[0][i].item(), 4) for i in range(len(labels))}

            return {
                "doc_type": labels[pred_idx],
                "confidence": round(confidence, 4),
                "all_scores": all_scores,
            }
        except Exception as e:
            logger.error(f"VLM classification failed: {e}")
            return {"doc_type": "other", "confidence": 0.0, "all_scores": {}, "error": str(e)}

    def classify_page_role(self, image: Image.Image, page_num: int, total_pages: int) -> str:
        """Heuristic page role classification (Sherlock-style).
        Uses position + VLM features to determine if a page is a document boundary."""
        if total_pages == 1:
            return "single_page"

        self._load_model()
        if not self._loaded:
            # Fallback: position-based heuristic
            if page_num == 1:
                return "first_page"
            elif page_num == total_pages:
                return "last_page"
            return "mid_page"

        try:
            import torch
            encoding = self._processor(image, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model(**encoding)
            probs = torch.softmax(outputs.logits, dim=-1)
            max_conf = probs.max().item()

            # High confidence on a new page type suggests document boundary
            if page_num == 1:
                return "first_page"
            elif page_num == total_pages:
                return "last_page"
            elif max_conf > 0.6:
                # Strong classification signal mid-document = likely new document start
                return "first_page"
            return "mid_page"
        except Exception:
            if page_num == 1:
                return "first_page"
            elif page_num == total_pages:
                return "last_page"
            return "mid_page"

    def classify_all_pages(self, images: list[Image.Image]) -> list[dict]:
        """Classify every page — type + role. Sherlock-style per-page analysis."""
        total = len(images)
        results = []
        for i, image in enumerate(images):
            page_num = i + 1
            classification = self.classify_document(image)
            role = self.classify_page_role(image, page_num, total)
            results.append({
                "page": page_num,
                "doc_type": classification["doc_type"],
                "confidence": classification["confidence"],
                "all_scores": classification.get("all_scores", {}),
                "role": role,
            })
            logger.info(f"Page {page_num}/{total}: type={classification['doc_type']} "
                        f"conf={classification['confidence']:.3f} role={role}")
        return results

    def extract_layout_features(self, image: Image.Image) -> dict:
        self._load_model()
        if not self._loaded:
            return {"words": [], "boxes": [], "error": "Model not loaded"}

        try:
            encoding = self._processor(image, return_tensors="pt", truncation=True, max_length=512)
            words = encoding.get("input_ids", [])
            return {
                "token_count": len(words[0]) if len(words) > 0 else 0,
                "has_layout": True,
                "source": "vlm",
            }
        except Exception as e:
            logger.error(f"VLM feature extraction failed: {e}")
            return {"words": [], "boxes": [], "error": str(e)}


vlm_service = VLMService()
