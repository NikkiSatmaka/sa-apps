"""Pembuat identifier netral (tanpa dependensi ke service/API) agar tidak ada impor siklik."""

import random
import string
from datetime import datetime, timezone


def generate_doc_id() -> str:
    """Generate ID dokumen unik dengan format DOC-{YYYYMMDD}-{random6}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"DOC-{date_part}-{random_part}"
