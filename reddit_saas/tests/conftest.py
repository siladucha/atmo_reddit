"""Shared test fixtures."""

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models import *  # noqa: F401,F403


# Use the real local DB for integration tests
TEST_DB_URL = "postgresql://user@localhost:5432/reddit_saas"
engine = create_engine(TEST_DB_URL)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Create all tables once for the test session."""
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    """Provide a DB session that rolls back after each test.

    Uses SQLAlchemy 2.0 nested transaction (SAVEPOINT) pattern:
    - Outer real transaction wraps the entire test
    - session.commit() releases savepoints, not the outer transaction
    - session.close() is intercepted to prevent premature deassociation
    - Final rollback undoes everything
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestSession(bind=connection, join_transaction_mode="create_savepoint")

    # Prevent tested code from closing our session (Celery tasks call db.close()
    # in their finally block which would deassociate the transaction).
    _real_close = session.close
    session.close = lambda: None

    yield session

    # Restore and cleanup
    session.close = _real_close
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    """Provide a FastAPI test client with DB override and auth cookie."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        # Register and login to get auth cookie
        c.post("/auth/register", json={"email": "test@fixture.com", "password": "testpass"})
        r = c.post("/login", data={"email": "test@fixture.com", "password": "testpass"}, follow_redirects=False)
        if "access_token" in r.cookies:
            c.cookies.set("access_token", r.cookies["access_token"])
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def superuser(db):
    """Create a superuser for admin tests."""
    from app.services.auth import create_user
    user = create_user(db, email="admin@test.com", password="admin123", full_name="Admin")
    user.is_superuser = True
    user.role = "owner"
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db):
    """Create a regular (non-superuser) user."""
    from app.services.auth import create_user
    return create_user(db, email="user@test.com", password="user123", full_name="User")


@pytest.fixture
def admin_client(db, superuser):
    """TestClient authenticated as superuser."""
    from app.services.auth import create_access_token

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(data={
        "sub": str(superuser.id),
        "email": superuser.email,
        "role": superuser.user_role.value,
        "is_superuser": superuser.is_superuser,
    })
    with TestClient(app) as c:
        c.cookies.set("access_token", token)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def regular_client(db, regular_user):
    """TestClient authenticated as regular (non-superuser) user."""
    from app.services.auth import create_access_token

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(data={
        "sub": str(regular_user.id),
        "email": regular_user.email,
        "role": regular_user.user_role.value,
        "is_superuser": regular_user.is_superuser,
    })
    with TestClient(app) as c:
        c.cookies.set("access_token", token)
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Scrape Queue fixtures (fakeredis)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis():
    """In-memory Redis for unit tests (no real Redis required)."""
    import fakeredis
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def rate_limiter(fake_redis):
    """ScrapeRateLimiter instance backed by fakeredis."""
    from app.services.rate_limiter import ScrapeRateLimiter
    return ScrapeRateLimiter(fake_redis)


@pytest.fixture
def distributed_lock(fake_redis):
    """ScrapeDistributedLock instance backed by fakeredis."""
    from app.services.distributed_lock import ScrapeDistributedLock
    return ScrapeDistributedLock(fake_redis)
