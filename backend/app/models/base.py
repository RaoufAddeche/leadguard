from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Timezone-aware UTC now (``datetime.utcnow`` is deprecated)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
