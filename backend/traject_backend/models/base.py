"""SQLAlchemy declarative base for all Axon backend ORM models.

All model classes in ``traject_backend.models`` inherit from :class:`Base`.
The shared metadata object is used by Alembic for schema migrations and by
``init_db()`` for table creation.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all Axon backend ORM models.

    All four model classes (``InferenceSpanRecord``, ``CostAttributionRecord``,
    ``BudgetControlRecord``, ``CacheEntryRecord``) inherit from this class.
    """
