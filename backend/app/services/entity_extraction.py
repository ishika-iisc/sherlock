import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PATTERNS = {
    "invoice_number": [
        (r"(?i)invoice\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Z0-9][\w\-]{2,20})", 0.90),
        (r"(?i)inv\s*[:\-#]\s*([A-Z0-9][\w\-]{2,20})", 0.80),
    ],
    "contract_number": [
        (r"(?i)contract\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Z0-9][\w\-]{1,20})", 0.90),
    ],
    "amendment_number": [
        (r"(?i)amendment\s*(?:#|no\.?|number)\s*[:\-]?\s*(\d{1,5})", 0.85),
    ],
    "date": [
        (r"(?i)(?:dated?|effective|signed|as of)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", 0.90),
        (r"(?i)(?:dated?|effective|signed|as of)\s*[:\-]?\s*(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})", 0.90),
        (r"(?i)((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})", 0.80),
        (r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})", 0.65),  # Ambiguous — lower confidence
    ],
    "amount": [
        (r"(?i)(?:total|amount|sum|balance|due|value|price)\s*[:\-]?\s*[\$\£\€]?\s*([\d,]+\.\d{2})", 0.90),
        (r"[\$\£\€]\s*([\d,]+\.\d{2})", 0.80),
        (r"(?i)(?:usd|gbp|eur|inr)\s*[\$\£\€]?\s*([\d,]+\.\d{2})", 0.85),
    ],
    "vendor_name": [
        (r"(?i)(?:vendor|supplier)\s*[:\-]\s*([A-Z][\w\s&.,]{2,50}?)(?:\s*[\n(])", 0.80),
        (r"(?i)(?:from|bill\s*from)\s*[:\-]\s*([A-Z][\w\s&.]{2,40}?)(?:\s*[\n(,])", 0.70),
    ],
    "buyer_name": [
        (r"(?i)(?:buyer|customer|client|bill\s*to|ship\s*to)\s*[:\-]\s*([A-Z][\w\s&.,]{2,50}?)(?:\s*[\n(])", 0.80),
    ],
    "parties": [
        (r"(?i)between\s+([A-Z][\w\s&.,()]+?)\s+and\s+([A-Z][\w\s&.,()]+?)(?:\s*[\n.])", 0.85),
    ],
    "email": [
        (r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", 0.95),
    ],
    "phone": [
        (r"(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}", 0.80),
    ],
    "po_number": [
        (r"(?i)(?:po|purchase\s*order)\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Z0-9][\w\-]{2,20})", 0.90),
    ],
    "vat_number": [
        (r"(?i)vat\s*(?:reg(?:istered)?)?\.?\s*(?:no\.?|number)?\s*[:\-]?\s*([A-Z]{2}\s*\d[\w\s]{3,20})", 0.85),
    ],
    "registered_number": [
        (r"(?i)registered\s*(?:no\.?|number)\s*[:\-]?\s*([\w\-]{2,20})", 0.80),
    ],
}

MAX_VALUE_LENGTH = 80


def extract_entities(text: str) -> list[dict]:
    """Extract entities with calibrated confidence per pattern."""
    entities = []
    for field_name, patterns in PATTERNS.items():
        found = False
        for pattern, base_confidence in patterns:
            if found:
                break
            for match in re.finditer(pattern, text):
                if field_name == "parties" and match.lastindex and match.lastindex >= 2:
                    value = f"{match.group(1).strip()} and {match.group(2).strip()}"
                elif match.lastindex:
                    value = match.group(1)
                else:
                    value = match.group(0)

                value = value.strip().rstrip(".,;:")
                if len(value) < 2 or len(value) > MAX_VALUE_LENGTH:
                    continue

                # Calibrate: context keywords boost confidence
                confidence = base_confidence
                context_start = max(0, match.start() - 50)
                context = text[context_start:match.end() + 50].lower()
                context_keywords = ["invoice", "contract", "total", "amount", "date",
                                    "vendor", "buyer", "email", "phone", "po", "vat"]
                if any(kw in context for kw in context_keywords):
                    confidence = min(confidence + 0.05, 0.98)

                entities.append({
                    "field_name": field_name,
                    "field_value": value,
                    "confidence": round(confidence, 4),
                    "source": "regex",
                    "span": [match.start(), match.end()],
                })
                found = True
                break

    # Multiple emails
    emails = set()
    for match in re.finditer(r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", text):
        emails.add(match.group(1))
    entities = [e for e in entities if e["field_name"] != "email"]
    for email in sorted(emails):
        entities.append({
            "field_name": "email",
            "field_value": email,
            "confidence": 0.95,
            "source": "regex",
            "span": [0, 0],
        })

    return entities


def normalize_date(date_str: str) -> str | None:
    formats = ["%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y",
               "%d.%m.%Y", "%m.%d.%Y", "%d %B %Y", "%d %b %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def normalize_amount(amount_str: str) -> str:
    cleaned = re.sub(r"[^\d.]", "", amount_str)
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return amount_str


def normalize_entities(entities: list[dict]) -> list[dict]:
    for e in entities:
        if e["field_name"] == "date":
            normalized = normalize_date(e["field_value"])
            if normalized:
                e["field_value"] = normalized
        elif e["field_name"] == "amount":
            e["field_value"] = normalize_amount(e["field_value"])
    return entities
