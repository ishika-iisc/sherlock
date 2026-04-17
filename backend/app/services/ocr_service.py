import logging
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)


class OCRService:
    """Extracts text from images/scanned documents using Tesseract and EasyOCR."""

    def __init__(self):
        self._easyocr_reader = None

    @property
    def easyocr_reader(self):
        if self._easyocr_reader is None:
            import easyocr
            self._easyocr_reader = easyocr.Reader(["en"], gpu=False)
        return self._easyocr_reader

    def extract_with_tesseract(self, image: Image.Image) -> dict:
        try:
            import pytesseract
            text = pytesseract.image_to_string(image)
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            words = []
            for i, word in enumerate(data["text"]):
                if word.strip():
                    words.append({
                        "text": word,
                        "confidence": float(data["conf"][i]) / 100.0,
                        "bbox": [data["left"][i], data["top"][i],
                                 data["left"][i] + data["width"][i],
                                 data["top"][i] + data["height"][i]],
                    })
            return {"full_text": text, "words": words, "source": "tesseract"}
        except Exception as e:
            logger.error(f"Tesseract failed: {e}")
            return {"full_text": "", "words": [], "source": "tesseract", "error": str(e)}

    def extract_with_easyocr(self, image_path: str) -> dict:
        try:
            results = self.easyocr_reader.readtext(image_path)
            words = []
            full_text_parts = []
            for bbox, text, conf in results:
                flat_bbox = [int(bbox[0][0]), int(bbox[0][1]), int(bbox[2][0]), int(bbox[2][1])]
                words.append({"text": text, "confidence": float(conf), "bbox": flat_bbox})
                full_text_parts.append(text)
            return {"full_text": " ".join(full_text_parts), "words": words, "source": "easyocr"}
        except Exception as e:
            logger.error(f"EasyOCR failed: {e}")
            return {"full_text": "", "words": [], "source": "easyocr", "error": str(e)}

    def extract(self, image: Image.Image, image_path: str | None = None) -> dict:
        tesseract_result = self.extract_with_tesseract(image)
        if image_path:
            easyocr_result = self.extract_with_easyocr(image_path)
        else:
            # Save temp image for easyocr
            tmp = Path("/tmp/ocr_temp.png")
            image.save(tmp)
            easyocr_result = self.extract_with_easyocr(str(tmp))

        # Pick the result with more text content
        if len(easyocr_result["full_text"]) > len(tesseract_result["full_text"]):
            best = easyocr_result
            best["alt_source"] = tesseract_result
        else:
            best = tesseract_result
            best["alt_source"] = easyocr_result

        return best


ocr_service = OCRService()
