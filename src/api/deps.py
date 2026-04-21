from collections.abc import Generator

from sqlmodel import Session

from src.db.session import get_session


def session_dep() -> Generator[Session, None, None]:
    yield from get_session()

