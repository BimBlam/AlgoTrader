"""
shared/db.py

SQLAlchemy 2.0 session factory and connection-pool management.
Every module that touches the database calls get_session() to obtain
a context-managed session; it never constructs an engine directly.
"""
from contextlib import contextmanager
from typing import Any, Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from algotrader.shared.exceptions import ConfigError, DataError

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def _build_engine(db_url: str) -> Engine:
    """
    Create a QueuePool engine tuned for single-workstation deployment:
    modest pool size and aggressive recycling to guard against stale
    connections after overnight idle periods.
    """
    engine = create_engine(
        db_url,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,   # recycle connections idle > 30 min
        pool_pre_ping=True,  # validate before handing a connection out
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _set_utc(dbapi_conn: Any, _record: Any) -> None:
        """Force UTC on every new DBAPI connection."""
        cursor = dbapi_conn.cursor()
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.close()

    return engine


def init_db(db_url: str) -> None:
    """
    Explicitly initialise the engine and verify connectivity.

    Normally called by each subsystem entry point after config is loaded.
    Falls back to lazy initialisation on the first get_session() call if
    not called explicitly.

    Args:
        db_url: PostgreSQL connection string.

    Raises:
        DataError: If the engine cannot be created or the DB is unreachable.
    """
    global _engine, _SessionLocal
    try:
        _engine = _build_engine(db_url)
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _SessionLocal = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    except Exception as exc:
        raise DataError(f"Failed to initialise database connection: {exc}") from exc


def _ensure_initialised() -> None:
    """Lazily initialise from config if init_db() was not called explicitly."""
    global _engine
    if _engine is not None:
        return
    try:
        from algotrader.shared.config_loader import get_config
        cfg = get_config()
        init_db(cfg.system.db_url)
    except (ConfigError, DataError):
        raise
    except Exception as exc:
        raise DataError(f"Unexpected error during lazy DB initialisation: {exc}") from exc


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Provide a transactional database session as a context manager.

    Commits on clean exit; rolls back on any exception so callers
    never need to manage transaction boundaries manually.

    Usage::

        with get_session() as session:
            session.add(my_object)

    Yields:
        A SQLAlchemy Session bound to the configured PostgreSQL engine.

    Raises:
        DataError: If lazy initialisation fails.
    """
    _ensure_initialised()
    assert _SessionLocal is not None
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine() -> Engine:
    """
    Return the raw Engine (e.g. for Alembic migrations or DDL).

    Raises:
        DataError: If the engine is not yet initialised.
    """
    _ensure_initialised()
    assert _engine is not None
    return _engine


def create_all_tables() -> None:
    """
    Create all ORM-defined tables that do not yet exist.

    For first-run setup and integration tests only; production schema
    management must use Alembic migrations.
    """
    from algotrader.shared.models import Base
    Base.metadata.create_all(get_engine())
