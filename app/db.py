"""SQLite engine + session. Applies migrations on startup."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, create_engine

from app.config import settings

engine = create_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def apply_migrations() -> None:
    """Run every .sql file in migrations/ in order. Idempotent by design
    (the files use IF NOT EXISTS)."""
    migrations_dir = Path(__file__).parent.parent / "migrations"
    if not migrations_dir.exists():
        return
    with engine.begin() as conn:
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            sql = sql_file.read_text()
            # sqlite's executescript handles multi-statement SQL
            raw = conn.connection.cursor()  # type: ignore[attr-defined]
            raw.executescript(sql)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(engine) as session:
        yield session
