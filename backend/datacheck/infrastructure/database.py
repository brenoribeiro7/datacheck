from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Authoritative metadata root for future Alembic-managed product models."""


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """Process-owned SQLAlchemy resources created and disposed as one unit."""

    engine: Engine
    session_factory: sessionmaker[Session]

    def dispose(self) -> None:
        self.engine.dispose()


def create_database_resources(database_url: str) -> DatabaseResources:
    """Create lazy database resources without opening a connection."""
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    return DatabaseResources(engine=engine, session_factory=session_factory)


def probe_database(engine: Engine) -> None:
    """Raise when PostgreSQL cannot serve a trivial query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()
