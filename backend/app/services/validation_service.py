import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Mock reference data (simulates ERP/CRM lookup)
MOCK_VENDORS = {"acme corp", "globex inc", "initech", "umbrella corp", "wayne enterprises"}
MOCK_PO_NUMBERS = {"PO-2024-001", "PO-2024-002", "PO-2024-100", "PO-2025-001"}


def validate_extractions(entities: list[dict]) -> list[dict]:
    """Validate extracted entities against business rules and mock reference data."""
    results = []
    for entity in entities:
        name = entity["field_name"]
        value = entity["field_value"]

        if name == "date":
            results.append(_validate_date(value))
        elif name == "amount":
            results.append(_validate_amount(value))
        elif name == "email":
            results.append(_validate_email(value))
        elif name == "vendor_name":
            results.append(_validate_vendor(value))
        elif name == "po_number":
            results.append(_validate_po(value))
        elif name == "invoice_number":
            results.append(_validate_invoice_number(value))
        else:
            results.append({
                "field_name": name, "extracted_value": value,
                "is_valid": True, "message": "No validation rule defined",
            })
    return results


def _validate_date(value: str) -> dict:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        is_future = dt > datetime.now()
        return {
            "field_name": "date", "extracted_value": value,
            "is_valid": not is_future,
            "message": "Date is in the future" if is_future else "Valid date",
        }
    except ValueError:
        return {"field_name": "date", "extracted_value": value, "is_valid": False, "message": "Invalid date format"}


def _validate_amount(value: str) -> dict:
    try:
        amt = float(value)
        if amt < 0:
            return {"field_name": "amount", "extracted_value": value, "is_valid": False, "message": "Negative amount"}
        if amt > 10_000_000:
            return {"field_name": "amount", "extracted_value": value, "is_valid": False,
                    "message": "Unusually large amount — needs review"}
        return {"field_name": "amount", "extracted_value": value, "is_valid": True, "message": "Valid amount"}
    except ValueError:
        return {"field_name": "amount", "extracted_value": value, "is_valid": False, "message": "Not a valid number"}


def _validate_email(value: str) -> dict:
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    valid = bool(re.match(pattern, value))
    return {"field_name": "email", "extracted_value": value, "is_valid": valid,
            "message": "Valid email" if valid else "Invalid email format"}


def _validate_vendor(value: str) -> dict:
    found = value.strip().lower() in MOCK_VENDORS
    return {"field_name": "vendor_name", "extracted_value": value,
            "is_valid": found, "message": "Vendor found in system" if found else "Vendor not found — verify manually"}


def _validate_po(value: str) -> dict:
    found = value.strip() in MOCK_PO_NUMBERS
    return {"field_name": "po_number", "extracted_value": value,
            "is_valid": found, "message": "PO matched" if found else "PO not found in system"}


def _validate_invoice_number(value: str) -> dict:
    valid = bool(re.match(r"^[A-Z0-9\-]{3,20}$", value))
    return {"field_name": "invoice_number", "extracted_value": value,
            "is_valid": valid, "message": "Valid format" if valid else "Unusual invoice number format"}
