import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def new_session() -> Session:
    get_engine()
    return _SessionLocal()


def set_tenant(db: Session, tenant_id: uuid.UUID | str | None) -> None:
    """Imposta il tenant corrente per la transazione: le policy RLS filtrano su questo valore.

    `set_config(..., true)` vale solo fino a fine transazione, quindi non "sporca"
    le connessioni restituite al pool.
    """
    db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": str(tenant_id) if tenant_id else ""},
    )


@contextmanager
def tenant_session(tenant_id: uuid.UUID | str) -> Iterator[Session]:
    """Sessione già legata a un tenant (per job e script)."""
    db = new_session()
    try:
        set_tenant(db, tenant_id)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
