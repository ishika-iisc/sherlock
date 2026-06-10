import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

REGEX_FIRST_FIELDS = {
    "invoice_number",
    "contract_number",
    "amendment_number",
    "date",
    "amount",
    "email",
    "phone",
    "po_number",
    "vat_number",
    "registered_number",
}

LLM_ASSISTED_FIELDS = {
    "vendor_name",
    "buyer_name",
    "parties",
    "contract_term",
    "payment_terms",
    "governing_law",
    "termination_notice",
    "liability_cap",
}

COMPANY_SUFFIXES = (
    "ltd",
    "limited",
    "llc",
    "inc",
    "corp",
    "corporation",
    "plc",
    "gmbh",
    "company",
    "co.",
    "co.,",
)

BAD_ENTITY_VALUES = {
    "provided",
    "the",
    "and",
    "shall",
    "agreement",
    "services",
    "service",
    "supplier",
    "buyer",
    "customer",
    "client",
}

PATTERNS = {
    "invoice_number": [
        (r"(?i)invoice\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Z0-9][\w\-]{2,20})", 0.90),
        (r"(?i)inv\s*[:\-#]\s*([A-Z0-9][\w\-]{2,20})", 0.80),
    ],
    "contract_number": [
        (r"(?i)contract\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Z0-9][\w\-]{1,20})", 0.90),
        (r"(?i)contract\s*(?:ref(?:erence)?|id)\s*[:#\-]?\s*([A-Z0-9][\w\-]{1,20})", 0.88),
    ],
    "amendment_number": [
        (r"(?i)amendment\s*(?:#|no\.?|number)\s*[:\-]?\s*(\d{1,5})", 0.85),
    ],
    "date": [
        (r"(?i)(?:dated?|effective|signed|as of)\s*[:\-]?\s*(\d{1,2}\s*[\/\-]\s*\d{1,2}\s*[\/\-]\s*\d{2,4})", 0.90),
        (r"(?i)(?:dated?|effective|signed|as of)\s*[:\-]?\s*(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})", 0.90),
        (r"(?i)((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})", 0.80),
        (r"(\d{1,2}\s*[\/\-]\s*\d{1,2}\s*[\/\-]\s*\d{4})", 0.65),  # Ambiguous — lower confidence
    ],
    "amount": [
        (r"(?i)(?:total|amount|sum|balance|due|value|price)\s*[:\-]?\s*[\$\£\€]?\s*([\d,]+\.\d{2})", 0.90),
        (r"[\$\£\€]\s*([\d,]+\.\d{2})", 0.80),
        (r"(?i)(?:usd|gbp|eur|inr)\s*[\$\£\€]?\s*([\d,]+\.\d{2})", 0.85),
    ],
    "vendor_name": [
        (r"(?im)^(?:vendor|supplier)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,()'\- ]{3,100})\s*$", 0.84),
        (r"(?im)^(?:from|bill\s*from)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,()'\- ]{3,100})\s*$", 0.74),
        (r"(?im)^\(\s*2\s*\)\s*([A-Z][A-Za-z0-9&.,()'\- ]{3,100})\s*$", 0.78),
    ],
    "buyer_name": [
        (r"(?im)^(?:buyer|customer|client|bill\s*to|ship\s*to|organisation)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,()'\- ]{3,100})\s*$", 0.82),
        (r"(?im)^\(\s*1\s*\)\s*([A-Z][A-Za-z0-9&.,()'\- ]{3,100})\s*$", 0.80),
    ],
    "parties": [
        (r"(?is)between\s+([A-Z][A-Za-z0-9&.,()'\- ]{3,120}?)\s+and\s+([A-Z][A-Za-z0-9&.,()'\- ]{3,120}?)(?=\s*\n)", 0.82),
        (r"(?is)^\(\s*1\s*\)\s*([^\n]{3,120}?)\s*$.*?^\(\s*2\s*\)\s*([^\n]{3,120}?)\s*$", 0.88),
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
    "contract_term": [
        (r"(?i)(?:initial\s+term|contract\s+term|term)\s*(?:shall\s+be|is|:|\-)?\s*([^.:\n]{3,180}?(?:year|years|month|months|day|days)[^.:\n]{0,80})", 0.78),
        (r"(?i)(?:commenc(?:e|ing)|starts?)\s+on\s+([^.:\n]{3,180}?(?:until|expire|expires|ending|end)[^.:\n]{3,120})", 0.72),
    ],
    "payment_terms": [
        (r"(?i)payment\s+terms?\s*(?:are|shall\s+be|:|\-)?\s*([^.:\n]{3,180})", 0.82),
        (r"(?i)\b(?:net|within)\s+(\d{1,3}\s+days(?:\s+of\s+[^.:\n]{3,120})?)", 0.80),
        (r"(?i)invoice(?:s)?\s+(?:shall\s+be\s+)?(?:paid|payable)\s+([^.:\n]{3,180})", 0.76),
    ],
    "governing_law": [
        (r"(?i)governed\s+by\s+(?:and\s+construed\s+in\s+accordance\s+with\s+)?(?:the\s+)?laws?\s+of\s+([A-Za-z ,]{3,80})", 0.84),
        (r"(?i)jurisdiction\s+(?:of|in)\s+([A-Za-z ,]{3,80})", 0.70),
    ],
    "termination_notice": [
        (r"(?i)(\d{1,3}\s+days?['’]?\s+(?:prior\s+)?written\s+notice)", 0.84),
        (r"(?i)terminat(?:e|ion)[^.:\n]{0,80}?(\d{1,3}\s+days?[^.:\n]{0,120})", 0.76),
    ],
    "liability_cap": [
        (r"(?i)(?:liability|aggregate\s+liability)[^.:\n]{0,120}?(?:cap|limited\s+to|shall\s+not\s+exceed)\s*([^.:\n]{3,180})", 0.78),
        (r"(?i)(?:shall\s+not\s+exceed)\s*([\$£€]?\s*[\d,]+(?:\.\d{2})?|[^.:\n]{3,160})", 0.72),
    ],
}

MAX_VALUE_LENGTH = 80
EXTENDED_VALUE_FIELDS = {
    "contract_term",
    "payment_terms",
    "governing_law",
    "termination_notice",
    "liability_cap",
}


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip(".,;:")


def _looks_like_company_name(value: str) -> bool:
    lowered = value.lower()
    if any(token in lowered for token in COMPANY_SUFFIXES):
        return True

    words = [word for word in re.split(r"\s+", value) if word]
    capitalized_words = sum(1 for word in words if word[:1].isupper())
    return len(words) >= 2 and capitalized_words >= 2


def _is_bad_entity_value(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in BAD_ENTITY_VALUES:
        return True
    if len(lowered.split()) == 1 and lowered.isalpha() and len(lowered) < 10:
        return True
    return False


def _is_plausible_value(field_name: str, value: str) -> bool:
    if _is_bad_entity_value(value):
        return False
    lowered = value.lower()

    if field_name in {"vendor_name", "buyer_name"}:
        return _looks_like_company_name(value)

    if field_name == "parties":
        if " and " not in value.lower():
            return False
        left, right = [part.strip() for part in re.split(r"(?i)\sand\s", value, maxsplit=1)]
        return _looks_like_company_name(left) and _looks_like_company_name(right)

    if field_name == "payment_terms":
        if lowered.startswith(("for the related", "for cr", "and the cost")):
            return False
        return bool(re.search(r"\b(?:net\s*)?\d{1,3}\s+days?\b|\binvoice\b|\bpaid\b|\bpayable\b|\bdue\b", lowered))

    if field_name == "governing_law":
        return bool(re.search(r"[a-zA-Z]{3,}", value))

    if field_name == "liability_cap":
        return bool(re.search(r"[\d£$€]", value)) or len(value.split()) >= 2

    if field_name in EXTENDED_VALUE_FIELDS:
        return len(value.split()) >= 2

    return True


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

                value = _normalize_whitespace(value)
                max_length = 220 if field_name in EXTENDED_VALUE_FIELDS else MAX_VALUE_LENGTH
                if len(value) < 2 or len(value) > max_length:
                    continue
                if not _is_plausible_value(field_name, value):
                    logger.info("Skipping implausible %s candidate: %r", field_name, value)
                    continue

                # Calibrate: context keywords boost confidence
                confidence = base_confidence
                context_start = max(0, match.start() - 50)
                context = text[context_start:match.end() + 50].lower()
                context_keywords = ["invoice", "contract", "total", "amount", "date",
                                    "vendor", "buyer", "email", "phone", "po", "vat",
                                    "term", "payment", "governing", "termination",
                                    "liability", "amendment", "agreement"]
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
               "%d.%m.%Y", "%m.%d.%Y", "%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%d -%m-%Y", "%d- %m-%Y",
               "%d - %m - %Y", "%d/%m/%y", "%d-%m-%y"]
    cleaned = re.sub(r"\s*([/-])\s*", r"\1", date_str.strip())
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
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
