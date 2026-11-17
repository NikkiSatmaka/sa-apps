"""Small shared helpers for project API response construction."""

import uuid
from typing import Optional

from app.models.user import User


def _ringkas_orang(user: Optional[User], user_id: Optional[uuid.UUID]) -> Optional[dict]:
    """Ringkasan orang pada project (id+nama+email); None bila tidak ada orangnya."""
    if user_id is None:
        return None
    return {
        "id": str(user_id),
        "name": user.name if user else None,
        "email": user.email if user else None,
    }
