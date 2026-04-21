from __future__ import annotations

from sqlalchemy import Engine, text
from sqlmodel import Session


def apply_runtime_migrations(engine: Engine) -> None:
    with Session(engine) as session:
        _ensure_column(session, "market", "end_at", "TIMESTAMP")
        _ensure_column(session, "order", "fill_price", "FLOAT")
        _ensure_column(session, "order", "fill_size", "FLOAT")
        _ensure_column(session, "order", "filled_at", "TIMESTAMP")
        _ensure_column(session, "position", "realized_pnl", "FLOAT DEFAULT 0")
        _ensure_column(session, "position", "exit_price", "FLOAT")
        _ensure_column(session, "position", "last_mark_price", "FLOAT")
        _ensure_column(session, "position", "last_marked_at", "TIMESTAMP")
        _ensure_column(session, "pricesnapshot", "yes_spread", "FLOAT")
        _ensure_column(session, "pricesnapshot", "no_spread", "FLOAT")
        session.commit()


def _ensure_column(session: Session, table_name: str, column_name: str, ddl_type: str) -> None:
    quoted_table = _quote_identifier(table_name)
    quoted_column = _quote_identifier(column_name)
    rows = session.exec(text(f"PRAGMA table_info({quoted_table})")).all()
    existing_columns = {row[1] for row in rows}
    if column_name in existing_columns:
        return
    session.exec(text(f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {ddl_type}"))


def _quote_identifier(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'
