from collections.abc import Generator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from src.db.migrations import apply_runtime_migrations
from src.common.settings import get_settings


def _build_engine():
    settings = get_settings()
    connect_args = {}
    sqlite_file_db = False
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30
        sqlite_file_db = settings.database_url not in {"sqlite://", "sqlite:///:memory:"}
    engine = create_engine(
        settings.database_url,
        echo=settings.sql_echo,
        connect_args=connect_args,
    )
    if settings.database_url.startswith("sqlite"):
        event.listen(
            engine,
            "connect",
            _configure_sqlite_connection(sqlite_file_db=sqlite_file_db),
        )
    return engine


def _configure_sqlite_connection(*, sqlite_file_db: bool):
    def _listener(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA foreign_keys = ON")
        if sqlite_file_db:
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.close()

    return _listener


engine = _build_engine()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    apply_runtime_migrations(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
