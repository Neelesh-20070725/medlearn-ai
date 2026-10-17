"""
Shared pytest fixtures for the MedLearn AI test suite.

main.py's DB models use PostgreSQL-specific column types (UUID, JSONB,
pgvector's Vector) that SQLite can't represent directly. Rather than
require a real Postgres instance for every test run (slow, and not
available in most CI environments without extra setup), these fixtures
swap each model's __table__ for a SQLite-compatible mirror built with
SQLAlchemy's generic, dialect-agnostic types - the same approach used
throughout this project's development-time verification. This is a
genuine tradeoff: it tests the application LOGIC (auth, safety filter,
rate limiting, search ranking, etc.) against real code paths, but does
NOT test Postgres-specific behavior (JSONB query operators, pgvector
similarity search itself). test_rag_retrieval-style tests that need real
vector search are out of scope for this suite - see main.py's
vector_search(), which is exercised in this project only via manual
verification against a real Postgres+pgvector instance, not here.
"""
import os
import sys
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# main.py needs *some* DATABASE_URL/JWT_SECRET to construct its Settings
# object at import time, even though we immediately replace the engine's
# usage with an in-memory SQLite DB below - same pattern as the CI
# workflow's placeholder env vars.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/medlearn_test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ["TESTING"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as app_module  # noqa: E402


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite DB per test, with SQLite-compatible
    mirrors of the tables each test module actually needs. Individual
    test files request this fixture and then swap in only the tables
    they use via the helper functions below - keeps each test file
    explicit about its own dependencies rather than one giant fixture
    building every table for every test."""
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session, engine
    session.close()


def make_users_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "users", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("email", sa.String, unique=True, nullable=False),
        sa.Column("hashed_password", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False, default="student"),
        sa.Column("is_verified", sa.Boolean, default=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime),
    )


def make_lessons_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "lessons", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("topic", sa.String, nullable=False),
        sa.Column("level", sa.String, nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("model_versions", sa.JSON, nullable=False),
        sa.Column("safety_flags", sa.JSON, nullable=False, default=list),
        sa.Column("created_at", sa.DateTime),
    )


def make_search_history_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "search_history", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", sa.Uuid(as_uuid=True)),
        sa.Column("query", sa.String, nullable=False),
        sa.Column("level", sa.String, nullable=False),
        sa.Column("found_result", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
    )


def make_audit_logs_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "audit_logs", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("actor_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("target_type", sa.String, nullable=False),
        sa.Column("target_id", sa.String, nullable=False),
        sa.Column("details", sa.JSON, nullable=False, default=dict),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
    )


def make_feedback_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "feedback", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("lesson_id", sa.Uuid(as_uuid=True)),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=False, default="open"),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
    )


def make_user_lesson_history_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "user_lesson_history", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", sa.Uuid(as_uuid=True)),
        sa.Column("lesson_id", sa.Uuid(as_uuid=True)),
        sa.Column("viewed_at", sa.DateTime, default=sa.func.now()),
        sa.Column("last_viewed_at", sa.DateTime, default=sa.func.now()),
        sa.Column("quiz_score", sa.Float, nullable=True),
        sa.Column("quiz_attempts", sa.Integer, default=0),
        sa.Column("completed", sa.Boolean, default=False),
        sa.Column("bookmarked", sa.Boolean, default=False),
    )


def make_tutor_messages_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "tutor_messages", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("lesson_id", sa.Uuid(as_uuid=True)),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, default=sa.func.now()),
    )


@pytest.fixture
def app():
    """The main.py module itself, for tests that just need to call its
    functions and don't need DB tables swapped (safety filter, JWT/hash
    logic, rate limiting - all pure logic with no DB dependency)."""
    return app_module
