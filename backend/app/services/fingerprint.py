"""Data integrity: a stable SHA-256 fingerprint of the identifying fields.

Used to prove a stored lead has not been altered since intake, and as a fast
exact-match key. Only the identifying fields are hashed — the free-text
description is excluded so that reformatting it does not change the identity.
"""

import hashlib
import json

from app.schemas.lead import LeadCreate

FINGERPRINT_FIELDS = ("firstname", "lastname", "email", "phone", "postal_code")


def compute_fingerprint(lead: LeadCreate) -> str:
    data = {
        "firstname": lead.firstname.strip().lower(),
        "lastname": lead.lastname.strip().lower(),
        "email": str(lead.email).strip().lower(),
        "phone": normalize_phone(lead.phone),
        "postal_code": lead.postal_code.strip(),
        "consent": lead.consent,
        "source": lead.source.strip().lower(),
    }
    # sort_keys makes the digest independent of dict ordering.
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def normalize_phone(phone: str) -> str:
    """Strip formatting and normalise +33 to a leading 0 for comparison."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("0033"):
        digits = "0" + digits[4:]
    elif digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits


def normalize_email(email: str) -> str:
    return str(email).strip().lower()
