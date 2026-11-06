"""Shared conservative identifier screening; cannot guarantee anonymity."""
import re

def is_safe_profile_value(value):
    """Reject obvious identifiers from proposed caregiver profile values."""
    if not isinstance(value, str):
        return False

    import unicodedata
    value = unicodedata.normalize("NFKC", value).strip()
    if any(unicodedata.category(c).startswith("C") for c in value):
        return False

    if not value or len(value) > 300:
        return False

    patterns = [
        r"https?://|www[.]|@",
        r"\b(?:my name is|name:|passport|nric|fin number|address:|contact me)\b",
        r"(?<!\d)(?:\d[ .()-]*){7,}(?!\d)",
        # Email addresses
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",

        # Singapore telephone numbers, with optional country code
        r"(?<!\d)(?:\+65[\s-]?)?[3689]\d{3}[\s-]?\d{4}(?!\d)",

        # NRIC / FIN-like identifiers
        r"\b[STFGM]\d{7}[A-Z]\b",

        # Singapore postal codes with contextual labels
        r"\b(?:postal\s*code|postcode|postal)\s*(?:is|:|#)?\s*\d{6}\b",

        # Common street address structures
        r"\b\d{1,4}\s+[\w\s]{2,45}\s+"
        r"(?:street|road|avenue|drive|lane|crescent|"
        r"boulevard|close|walk|place|terrace)\b",

        # HDB/unit-style identifiers
        r"(?<!\w)#\d{1,3}-\d{1,4}\b",

        # International numbers with explicit country code
        r"(?<!\w)\+\d{1,3}[\s-]?"
        r"(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{2,4}\b",
    ]

    return not any(
        re.search(pattern, value, re.IGNORECASE)
        for pattern in patterns
    )
