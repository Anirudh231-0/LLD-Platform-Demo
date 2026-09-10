import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.domain import Base


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite DB per test, fully isolated."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session, monkeypatch):
    """FastAPI TestClient wired to the in-memory test DB via dependency override."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
