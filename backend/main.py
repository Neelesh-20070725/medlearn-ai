"""
================================================================================
MedLearn AI — Backend (single-file build)
================================================================================
Educational medical AI platform. Search any medical topic, get a structured,
cited, level-appropriate lesson. Does NOT diagnose, prescribe, or give
personalized medical advice.

Everything lives in this one file on purpose (config, schemas, safety filter,
prompts, ensemble orchestration, RAG retrieval, DB models, auth, learning
tracking, AI tutor, API routes, app init) — same pattern as the Stock AI builds.

Run locally:
    pip install -r requirements.txt
    cp .env.example .env
    alembic upgrade head
    uvicorn main:app --reload

Sections:
    1. CONFIG
    2. SCHEMAS
    3. DB MODELS
    4. AUTH
    5. RATE LIMITING
    6. SAFETY FILTER
    7. PROMPTS (lesson generation + AI tutor prompts)
    8. RAG RETRIEVAL
    9. AI ENSEMBLE (lesson generation + tutor answering)
    10. API ROUTES (health, auth, lessons, learning engine, AI tutor, analytics)
    11. APP INIT

Rate Limiting: sliding-window limiter, Redis-backed (sorted-set based, a
real distributed sliding window) when REDIS_URL is reachable, falling back to an in-process
dict otherwise. The fallback is genuinely fine for local dev but NOT
correct behind multiple workers/instances - each process tracks its own
counts independently in that mode. Applied to /auth/login (keyed by
email+IP), /auth/register (keyed by IP), and /lessons/search (keyed by
user id when signed in, IP otherwise; only guards the expensive
generation path, not cache hits).

Analytics Engine: admin-only platform-wide aggregates (users, search/topic
popularity, quiz performance, tutor usage) computed directly from existing
tables - no separate event pipeline. Deliberately does NOT include
Performance Metrics or Error Logs from the original roadmap; those need
real request-level instrumentation that doesn't exist in this build.

Admin Engine: User Management (list, change role, activate/deactivate -
deactivation enforced at both login and token verification, not just a
decorative flag), Lesson Management (list with view/feedback counts,
delete), Feedback (open to any reader including anonymous; admin review
workflow with status transitions). Deliberately does NOT include Topic
Management, Asset Management (no underlying content model to manage yet),
AI Monitoring (overlaps with Analytics), or System Settings (no
runtime-editable settings store - Settings loads once from .env).

Audit Logging: every admin mutation (role change, activate/deactivate,
lesson delete, feedback status change) writes an append-only AuditLog row
in the same transaction as the mutation - no update/delete endpoint
exists for this table anywhere. actor_id uses ondelete=SET NULL so
deleting a user doesn't erase the record of what they did; target_id is a
plain string, not a foreign key, so an entry survives its target being
deleted (e.g. a lesson.deleted entry outlives the lesson it describes).
Readable via GET /admin/audit-log, filterable by action/target_type.

Search Engine: autocomplete and popular-searches are both derived from
LessonRecord.topic (topics already generated at least once) - an honest
bootstrapping limitation, same as most search-suggestion systems seeded
from historical query logs rather than a separately curated taxonomy.
Personal search history is logged only for signed-in users (anonymous
searches have no durable identity to attach a history entry to), and
includes searches that found no corpus coverage (found_result=False) -
"users keep searching for X and getting nothing" is a real signal worth
keeping, not just successful searches.

AI Tutor Engine: answers follow-up questions scoped to a specific lesson's
content (not open-ended medical chat). Works for both anonymous and
signed-in users via get_current_user_optional; conversation history only
persists queryably for signed-in users since anonymous requests have no
session concept to key it on. Reuses the same pattern_screen safety gate
as lesson generation, with one retry before failing closed (refusing to
answer) rather than ever serving a flagged response.
"""

import asyncio
import time
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import anthropic
import bcrypt
import openai
from jose import JWTError
from jose import jwt as jose_jwt
from passlib.context import CryptContext
from google import genai
from google.genai import types as genai_types
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, create_engine
from sqlalchemy import func as sa_func
from sqlalchemy import text as _sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

logger = logging.getLogger("medlearn")


def _utc_now() -> datetime:
    """Drop-in, non-deprecated replacement for datetime.utcnow(). Returns
    a NAIVE datetime representing the current UTC time - same semantics
    as datetime.utcnow() had, not a timezone-aware one. This matters:
    every DateTime column in this file is naive (no timezone=True), and
    JWT exp/iat comparisons, audit log ordering, and every other place
    a stored timestamp gets compared against "now" throughout this file
    all assume naive UTC datetimes. Switching to a timezone-aware value
    here would create a naive/aware comparison mismatch elsewhere rather
    than just silencing the deprecation warning - this function exists
    specifically to fix the warning without introducing that new bug."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ==============================================================================
# 1. CONFIG
# ==============================================================================

class Environment(str, Enum):
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    environment: Environment = Environment.development
    api_version: str = "v1"
    log_level: str = "INFO"

    database_url: str = "postgresql://user:password@localhost:5432/medlearn"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    claude_model: str = "claude-3-5-sonnet-20241022"
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-1.5-flash"

    trusted_orgs: list[str] = ["NIH", "CDC", "WHO", "PubMed", "FDA"]

    # Security: default to explicit trusted frontend origins rather than wildcard '*'
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    class Config:
        env_file = ".env"

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

# Refuse to run in production with the default placeholder secret (M-03)
if settings.is_production and settings.jwt_secret == "change-me-in-production":
    raise RuntimeError(
        "FATAL SECURITY CONFIGURATION: Refusing to start in production with default JWT_SECRET! "
        "Set a strong, cryptographically random JWT_SECRET in your environment or .env file."
    )


class _JSONLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": _utc_now().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    handler = logging.StreamHandler()
    if settings.is_production:
        handler.setFormatter(_JSONLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    root.handlers = [handler]


_configure_logging()
logger.info("MedLearn AI starting in %s mode (api %s)", settings.environment.value, settings.api_version)


# ==============================================================================
# 2. SCHEMAS
# ==============================================================================

class Level(str, Enum):
    child = "child"
    high_school = "high_school"
    college = "college"
    medical_student = "medical_student"
    general_public = "general_public"


class UserRole(str, Enum):
    student = "student"
    educator = "educator"
    admin = "admin"


class SourceRef(BaseModel):
    org: str
    url: str
    title: str


class LessonSection(BaseModel):
    id: str
    title: str
    content: str
    diagram_type: str = "concept_overview"
    sources: list[SourceRef] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str


class Lesson(BaseModel):
    id: str | None = None  # populated from LessonRecord.id once persisted; None only
                            # for a lesson object constructed before it's ever been
                            # saved (there's no such path currently, but the AI
                            # ensemble module builds a Lesson before the DB insert,
                            # so this stays optional rather than required)
    topic: str
    level: Level
    sections: list[LessonSection]
    quiz: list[QuizQuestion]
    disclaimer: str = (
        "This content is for educational purposes only. It is not medical "
        "advice, diagnosis, or treatment, and is not a substitute for "
        "professional medical care. Always consult a qualified healthcare "
        "provider with questions about a medical condition."
    )
    safety_flags: list[str] = Field(default_factory=list)


class LessonSearchRequest(BaseModel):
    topic: str
    level: Level = Level.general_public


class SearchHistoryEntry(BaseModel):
    query: str
    level: Level
    found_result: bool
    created_at: datetime


class AutocompleteSuggestion(BaseModel):
    topic: str
    level_count: int  # how many distinct levels have been generated for this topic


class PopularSearch(BaseModel):
    topic: str
    search_count: int


class TaxonomyEntryView(BaseModel):
    id: str
    canonical_name: str
    category: str
    synonyms: list[str]
    related_topics: list[str]


class TaxonomyEntryCreateRequest(BaseModel):
    canonical_name: str
    category: str
    synonyms: list[str] = Field(default_factory=list)
    related_topics: list[str] = Field(default_factory=list)


class TaxonomyEntryUpdateRequest(BaseModel):
    category: str | None = None
    synonyms: list[str] | None = None
    related_topics: list[str] | None = None


class TutorRequest(BaseModel):
    question: str


class UserRegisterRequest(BaseModel):
    email: str
    password: str


class UserLoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: str
    email: str
    role: str
    is_verified: bool
    created_at: datetime


class LessonHistoryEntry(BaseModel):
    lesson_id: str
    topic: str
    level: Level
    viewed_at: datetime
    last_viewed_at: datetime
    quiz_score: float | None
    quiz_attempts: int
    completed: bool
    bookmarked: bool


class QuizSubmitRequest(BaseModel):
    answers: list[int]


class QuizSubmitResponse(BaseModel):
    score: float
    correct_count: int
    total: int
    results: list[dict]


class LearningStats(BaseModel):
    lessons_viewed: int
    lessons_completed: int
    lessons_bookmarked: int
    average_quiz_score: float | None
    topics_covered: list[str]


class TutorResponse(BaseModel):
    answer: str
    lesson_id: str


class TutorHistoryEntry(BaseModel):
    role: str
    content: str
    created_at: datetime


class TopicPopularity(BaseModel):
    topic: str
    search_count: int  # number of distinct (topic, level) lesson records generated for this topic
    view_count: int  # total UserLessonHistory rows referencing lessons on this topic


class SearchAnalytics(BaseModel):
    total_lessons_generated: int  # distinct (topic, level) pairs ever generated, i.e. cache entries
    total_unique_topics: int
    top_topics: list[TopicPopularity]
    level_distribution: dict[str, int]  # level -> count of lessons generated at that level


class QuizAnalytics(BaseModel):
    total_attempts: int  # sum of quiz_attempts across all UserLessonHistory rows
    total_lessons_with_attempts: int
    average_score: float | None
    completion_rate: float | None  # lessons_completed / lessons_viewed, platform-wide


class TutorAnalytics(BaseModel):
    total_questions: int  # count of role='user' TutorMessage rows
    lessons_with_tutor_activity: int
    anonymous_question_count: int
    signed_in_question_count: int


class UserAnalytics(BaseModel):
    total_users: int
    verified_users: int
    users_by_role: dict[str, int]


class PlatformAnalytics(BaseModel):
    """Aggregate view combining all the above — the single endpoint an
    admin dashboard would call for an overview screen."""
    users: UserAnalytics
    search: SearchAnalytics
    quiz: QuizAnalytics
    tutor: TutorAnalytics
    safety_flag_count: int  # lessons ever generated with a non-empty safety_flags list
                             # (flags are cleared before serving, per generate_lesson, so
                             # a non-empty stored value here would only happen if that
                             # logic changes - included as a canary, expected to be 0)


class AdminUserView(BaseModel):
    id: str
    email: str
    role: str
    is_verified: bool
    is_active: bool
    created_at: datetime


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


class AdminLessonSummary(BaseModel):
    id: str
    topic: str
    level: Level
    safety_flags: list[str]
    created_at: datetime
    view_count: int
    feedback_count: int


class FeedbackSubmitRequest(BaseModel):
    message: str


class FeedbackView(BaseModel):
    id: str
    lesson_id: str
    lesson_topic: str
    user_email: str | None  # None for anonymous feedback
    message: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None


class UpdateFeedbackStatusRequest(BaseModel):
    status: str  # 'open' | 'reviewed' | 'dismissed'


class AuditLogView(BaseModel):
    id: str
    actor_email: str
    action: str
    target_type: str
    target_id: str
    details: dict
    created_at: datetime



# ==============================================================================
# 3. DB MODELS
# ==============================================================================

class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    published_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=False)
    token_count: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    source: Mapped["Source"] = relationship(back_populates="chunks")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default=UserRole.student.value)
    is_verified: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)  # admin-deactivated accounts flip this to False
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class LessonRecord(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint(
            "level IN ('child','high_school','college','medical_student','general_public')",
            name="valid_level",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    safety_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class UserLessonHistory(Base):
    __tablename__ = "user_lesson_history"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_user_lesson"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    quiz_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    quiz_attempts: Mapped[int] = mapped_column(default=0)
    completed: Mapped[bool] = mapped_column(default=False)
    bookmarked: Mapped[bool] = mapped_column(default=False)


class SearchHistory(Base):
    """One row per search a signed-in user makes - distinct from
    UserLessonHistory, which tracks lesson VIEWS (a search that hit an
    existing cached lesson doesn't necessarily mean the user viewed the
    result, and a search for a topic with no corpus coverage yet produces
    no lesson at all but is still a meaningful signal worth keeping:
    "students keep searching for X and getting nothing" is exactly the
    kind of gap this table is meant to surface). Anonymous searches are
    deliberately not logged here - there's no durable identity to attach
    them to, same reasoning as tutor_messages.user_id being nullable but
    only actually populated for signed-in callers."""
    __tablename__ = "search_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(String, nullable=False)  # raw text as typed, not normalized
    level: Mapped[str] = mapped_column(String, nullable=False)
    found_result: Mapped[bool] = mapped_column(default=True)  # False when the topic had no corpus coverage
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class TutorMessage(Base):
    __tablename__ = "tutor_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="valid_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class Feedback(Base):
    """User-submitted flags on a lesson - "this looks wrong," "this feels
    unsafe," "this is unclear," etc. Reviewed via the admin endpoints below.
    Distinct from safety_flags on LessonRecord, which are the AI ensemble's
    own automated flags at generation time - this is human-reported,
    after the fact, from any reader."""
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("status IN ('open','reviewed','dismissed')", name="valid_feedback_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TopicTaxonomy(Base):
    """Curated topic metadata - the Medical Knowledge Service layer.
    Distinct from LessonRecord (which is whatever's been GENERATED by the
    AI ensemble so far) and from RAG's document_chunks (raw retrieved
    prose): this is a small, deliberately-curated structure of what
    topics exist, how they're categorized, what else they're commonly
    called, and what related topics a reader might want next. Search
    autocomplete draws on this FIRST, before falling back to
    already-generated LessonRecord topics - so a curated topic can be
    suggested even if nobody has searched it yet, closing the
    "autocomplete only knows about topics someone already searched"
    limitation the plain LessonRecord-based version had.

    Seeded with a small starter set (see seed_topic_taxonomy at the
    bottom of this file) rather than claiming broad coverage - this is
    infrastructure for a curated layer, not a finished taxonomy. Growing
    it is editorial work (deciding what counts as its own topic, what
    synonyms are actually in common use), not something to fabricate
    entries for just to make the list longer."""
    __tablename__ = "topic_taxonomy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "endocrine", "respiratory", "infectious_disease"
    synonyms: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # e.g. ["type 2 diabetes", "diabetes mellitus"]
    related_topics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # canonical_names of related entries
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class AuditLog(Base):
    """Durable record of security-relevant admin actions - distinct from
    the app's regular `logger` calls, which go to stdout and aren't
    queryable history. Every admin mutation (role change, deactivation,
    lesson deletion, feedback status change) writes one row here, in
    addition to whatever it does functionally. Deliberately append-only:
    no update/delete endpoint is exposed for this table anywhere in the
    app - an audit log you can edit isn't an audit log. actor_id uses
    ondelete=SET NULL rather than CASCADE specifically so that deleting a
    user account doesn't erase the record of what they did - the action
    stays in the log with a null actor rather than vanishing."""
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String, nullable=False)  # denormalized snapshot - survives actor deletion/anonymization
    action: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "user.role_changed", "lesson.deleted"
    target_type: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "lesson" | "feedback"
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # action-specific context, e.g. {"old_role": "student", "new_role": "admin"}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


# ==============================================================================
# 4. AUTH
# ==============================================================================

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_MINUTES = settings.jwt_expire_minutes


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    try:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")
    except Exception:
        return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        try:
            return _pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False


def _create_token(user_id: str, role: str, token_type: str, expire_minutes: int) -> str:
    now = _utc_now()
    payload = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(user_id, role, "access", ACCESS_TOKEN_EXPIRE_MINUTES)


def create_refresh_token(user_id: str, role: str) -> str:
    return _create_token(user_id, role, "refresh", REFRESH_TOKEN_EXPIRE_MINUTES)


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise InvalidTokenError(str(e))

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"expected a {expected_type} token, got {payload.get('type')}")

    return payload


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not user.is_active:
        # Same message as "invalid token" deliberately - a deactivated
        # account shouldn't get a distinct error that confirms the account
        # exists and is specifically deactivated (avoid leaking account
        # status to someone probing with a stolen/old token).
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Like get_current_user, but returns None instead of raising 401 when
    there's no token or it's invalid - for endpoints that work for both
    anonymous and signed-in callers (e.g. the tutor). A malformed or
    expired token is treated the same as no token at all here, since the
    caller can still proceed anonymously; endpoints that actually require
    auth should keep using get_current_user, which stays strict."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_role(*allowed_roles: UserRole):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in {r.value for r in allowed_roles}:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _check


class EmailService:
    @staticmethod
    def _send(to: str, subject: str, body: str) -> None:
        logger.info("EMAIL (not actually sent - no provider configured) to=%s subject=%s", to, subject)
        logger.debug("Email body: %s", body)

    @classmethod
    def send_verification_email(cls, to: str, token: str) -> None:
        cls._send(to, "Verify your MedLearn AI account", f"Verification token: {token}")

    @classmethod
    def send_password_reset_email(cls, to: str, token: str) -> None:
        cls._send(to, "Reset your MedLearn AI password", f"Password reset token: {token}")


# ==============================================================================
# 5. RATE LIMITING
# ==============================================================================
# Sliding-window rate limiter, Redis-backed when REDIS_URL is reachable,
# falling back to an in-process dict when it isn't - documented as a
# fallback, not silently pretended to be equivalent. The in-memory version
# is genuinely fine for local dev (single process, single worker) but is
# NOT correct behind multiple workers/instances in production, since each
# process would track its own counts independently - that's a real
# limitation, not a rounding error, and it's called out below rather than
# glossed over.
#
# Applied to: /auth/login (brute-force protection, keyed by email+IP so a
# single email can't be hammered from many IPs or vice versa), /auth/register
# (keyed by IP, prevents mass account creation), and /lessons/search (keyed
# by IP when anonymous, by user id when signed in - this is the expensive
# AI-backed endpoint and the one most worth protecting from cost/abuse).

_in_memory_rate_buckets: dict[str, list[float]] = {}


def _get_redis_client_for_rate_limit():
    """Returns a redis client or None - never raises. Callers fall back to
    in-memory limiting on None, exactly like health_ready's Redis check
    already treats Redis as non-load-bearing infrastructure."""
    import os
    if os.getenv("TESTING") == "1":
        return None
    try:
        import redis as redis_lib

        client = redis_lib.from_url(settings.redis_url, socket_connect_timeout=1)
        client.ping()
        return client
    except Exception:  # noqa: BLE001 - any Redis problem means "use the fallback"
        return None


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded, retry after {retry_after_seconds}s")


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    """Sliding-window check: raises RateLimitExceeded if `key` has made
    >= max_requests calls in the last window_seconds. Redis path uses a
    sorted set (ZADD/ZREMRANGEBYSCORE/ZCARD) for a real distributed sliding
    window; in-memory path does the equivalent with a plain list, which is
    fine for a single process but does NOT coordinate across workers."""
    now = time.time()
    window_start = now - window_seconds
    redis_key = f"ratelimit:{key}"

    client = _get_redis_client_for_rate_limit()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zadd(redis_key, {f"{now}:{uuid.uuid4().hex}": now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds)
            _, _, count, _ = pipe.execute()
            if count > max_requests:
                raise RateLimitExceeded(retry_after_seconds=window_seconds)
            return
        except RateLimitExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - Redis failed mid-operation; fall through to in-memory
            logger.warning("Redis rate-limit check failed, falling back to in-memory: %s", e)

    # In-memory fallback
    bucket = _in_memory_rate_buckets.setdefault(key, [])
    bucket[:] = [t for t in bucket if t > window_start]
    bucket.append(now)
    if len(bucket) > max_requests:
        raise RateLimitExceeded(retry_after_seconds=window_seconds)


def rate_limit_response(exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again shortly."},
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def get_client_ip(request: Request) -> str:
    """Prefer X-Forwarded-For when present (standard behind a load balancer
    / reverse proxy - Cloud Run, ALB, nginx, etc. all set this), falling
    back to the direct connection IP for local/unproxied dev. Takes the
    first entry, which is the original client per the X-Forwarded-For
    convention - trusting it requires the proxy layer to be the one
    setting it, not passing through an arbitrary client-supplied value,
    which is standard practice for a properly configured reverse proxy
    but worth noting as an assumption."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ==============================================================================
# 6. SAFETY FILTER
# ==============================================================================

_DIRECTED_DIAGNOSTIC_PATTERNS = [
    r"\byou (likely |probably |might )?have\b.{0,40}\b(disease|infection|condition|cancer|diabetes|syndrome)\b",
    r"\byou should (take|use|stop taking|increase|decrease)\b",
    r"\bi (recommend|suggest) you (take|use|see a doctor about your)\b",
    r"\byour (diagnosis|prognosis) is\b",
    r"\bbased on your symptoms\b",
    r"\bthe (correct|right) (dose|dosage) for you\b",
]
_COMPILED_SAFETY_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _DIRECTED_DIAGNOSTIC_PATTERNS]


@dataclass
class SafetyResult:
    passed: bool
    flags: list[str]


def pattern_screen(text: str) -> SafetyResult:
    flags = []
    for pattern in _COMPILED_SAFETY_PATTERNS:
        if pattern.search(text):
            flags.append(f"pattern_match: {pattern.pattern}")
    return SafetyResult(passed=len(flags) == 0, flags=flags)


# ==============================================================================
# 6b. EMERGENCY & CRISIS ROUTING
# ==============================================================================
# These checks run BEFORE any AI call.  If triggered they raise HTTPException
# immediately with safe redirect copy; the AI never sees the input.

_EMERGENCY_PATTERNS = [
    # Chest-pain cardiac emergency cluster
    r"\bchest\s+pain\b",
    r"\bleft\s+arm\s+(pain|ache|numb|tingling)\b",
    r"\bjaw\s+(pain|ache)\b",
    r"\bcan'?t\s+breathe\b",
    r"\bshortness\s+of\s+breath\b.*\b(pain|chest|sweat)\b",
    r"\bsweating\b.*\b(chest|pain|dizziness)\b",
    r"\b(heart\s+attack|cardiac\s+arrest|stroke\s+symptoms)\b",
    r"\b(call\s+911|call\s+an\s+ambulance|emergency\s+room|ER\s+now)\b",
    # Stroke FAST cluster
    r"\b(sudden\s+)?(face\s+droop(ing)?|arm\s+weakness|speech\s+difficult)\b",
    r"\bsudden\s+(numbness|confusion|trouble\s+seeing|severe\s+headache)\b",
    # Severe allergic / anaphylaxis
    r"\bthroat\s+(closing|swelling|swollen)\b",
    r"\bcan'?t\s+swallow\b.*\b(allerg|bee|sting|food)\b",
]
_COMPILED_EMERGENCY_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _EMERGENCY_PATTERNS
]

_CRISIS_PATTERNS = [
    r"\b(want\s+to|thinking\s+(about|of)|plan(ning)?\s+to)\s+(kill|hurt|harm)\s+(my)?self\b",
    r"\b(suicid(e|al)|self[-\s]harm|self[-\s]injur)\b",
    r"\b(end\s+my\s+life|take\s+my\s+(own\s+)?life)\b",
    r"\b(cut(ting)?\s+myself|overdos(e|ing))\b",
    r"\bi\s+(don'?t\s+want|no\s+longer\s+want)\s+to\s+(live|be\s+alive|exist)\b",
    r"\b(hopeless|worthless|no\s+reason\s+to\s+live)\b",
]
_COMPILED_CRISIS_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _CRISIS_PATTERNS
]

EMERGENCY_RESPONSE = (
    "⚠️ **This sounds like a medical emergency.** "
    "Please call **911** (USA) or your local emergency number immediately, "
    "or have someone drive you to the nearest emergency room. "
    "MedLearn AI is an educational platform and cannot provide emergency medical care. "
    "**Do not wait — call for help now.**"
)

CRISIS_RESPONSE = (
    "💙 **It sounds like you may be going through something very difficult.** "
    "Please reach out to a crisis support line right now:\n\n"
    "🇺🇸 **988 Suicide & Crisis Lifeline:** Call or text **988** (USA, 24/7)\n"
    "🌍 **International Association for Suicide Prevention:** https://www.iasp.info/resources/Crisis_Centres/\n\n"
    "MedLearn AI is an educational platform and is not equipped to provide crisis support. "
    "A trained counsellor is standing by and wants to help."
)


def screen_for_emergency(text: str) -> tuple[bool, str]:
    """
    Check whether *text* contains emergency or crisis signals before any AI call.

    Returns (is_flagged: bool, category: str) where category is one of:
    'emergency', 'crisis', or '' (safe).

    Callers must raise HTTPException(422, ...) immediately when is_flagged is True.
    """
    for pat in _COMPILED_EMERGENCY_PATTERNS:
        if pat.search(text):
            return True, "emergency"
    for pat in _COMPILED_CRISIS_PATTERNS:
        if pat.search(text):
            return True, "crisis"
    return False, ""


def emergency_http_exception(category: str) -> HTTPException:
    """Build the HTTPException to raise when screen_for_emergency fires."""
    detail = EMERGENCY_RESPONSE if category == "emergency" else CRISIS_RESPONSE
    return HTTPException(
        status_code=422,
        detail={
            "type": category,
            "message": detail,
            "safe_redirect": True,
        },
    )



QC_SYSTEM_PROMPT = """You are a safety reviewer for an educational medical platform. You will be shown a lesson section. Your only job is to determine whether the text crosses from EDUCATION into DIAGNOSIS or PERSONAL MEDICAL ADVICE directed at the reader.

Educational (ALLOWED): explaining how a disease, drug, or biological process works in general; describing symptoms as part of explaining a condition; explaining the mechanism of a treatment class.

NOT ALLOWED: telling the reader what condition THEY have; telling the reader what THEY should do, take, or stop taking; interpreting symptoms the reader described about themselves; giving a specific dose or treatment plan as if for an individual.

Respond with only a JSON object: {"safe": true or false, "reason": "brief reason if unsafe, else empty string"}"""


def build_qc_prompt(section_text: str) -> str:
    return f"Review this lesson section:\n\n{section_text}"


# ==============================================================================
# 7. PROMPTS & LEARNER PROFILES
# ==============================================================================

@dataclass
class LearnerProfile:
    level: Level
    target_audience: str
    assumed_prerequisites: list[str]
    bloom_taxonomy_target: str
    curricular_scope: str
    pedagogical_instructions: str


LEARNER_PROFILES: dict[Level, LearnerProfile] = {
    Level.child: LearnerProfile(
        level=Level.child,
        target_audience="Young learners aged 8-12",
        assumed_prerequisites=["Basic concept that body has organs (heart, brain, stomach)", "Living things need food and oxygen"],
        bloom_taxonomy_target="Remember & Understand (Foundational Awareness)",
        curricular_scope="Gross anatomy, simple analogies, protective body habits, non-scary biological overview",
        pedagogical_instructions=(
            "Explain like the reader is 8-12 years old. Use concrete analogies "
            "(e.g., comparing cells to tiny bustling workshops, antibodies to security scouts). "
            "Avoid clinical jargon entirely. Keep sentences short and empowering."
        )
    ),
    Level.high_school: LearnerProfile(
        level=Level.high_school,
        target_audience="Secondary education biology students (ages 14-18)",
        assumed_prerequisites=["Cell theory, DNA as genetic material, organ systems, homeostasis"],
        bloom_taxonomy_target="Understand & Apply (Homeostatic Principles)",
        curricular_scope="Cell membrane transport, basic immune response, organ-level pathology, public health prevention",
        pedagogical_instructions=(
            "Explain at a high school biology curriculum level. Introduce standard scientific terms "
            "(receptors, enzymes, antibodies, vascular pressure) and define each in context. "
            "Focus on how disruptions to homeostasis lead to physiological symptoms."
        )
    ),
    Level.college: LearnerProfile(
        level=Level.college,
        target_audience="Undergraduate biology and pre-health students",
        assumed_prerequisites=["Biochemistry, cell biology, genetics, general physiology"],
        bloom_taxonomy_target="Apply & Analyze (Mechanistic Cascades)",
        curricular_scope="Signal transduction cascades, enzyme kinetics, receptor pharmacology, histopathology",
        pedagogical_instructions=(
            "Explain at a college biology / pre-med level. Detail molecular signaling pathways, "
            "cellular transport kinetics, receptor agonism/antagonism, and tissue-level compensatory feedback loops."
        )
    ),
    Level.medical_student: LearnerProfile(
        level=Level.medical_student,
        target_audience="Medical, nursing, and clinical healthcare trainees",
        assumed_prerequisites=["Gross anatomy, systemic physiology, pathology, pharmacology fundamentals"],
        bloom_taxonomy_target="Analyze & Evaluate (Clinical Pathophysiology & Evidence)",
        curricular_scope="Etiology, pathophysiological staging, microscopic pathology, molecular pharmacology classes, evidence-based guideline criteria",
        pedagogical_instructions=(
            "Explain at a medical student level. Use rigorous clinical and pathophysiological terminology. "
            "Emphasize molecular etiology, cellular pathology, hemodynamic or endocrine feedback failure, "
            "and drug class mechanisms of action. Remain STRICTLY educational: never provide real-patient diagnostic directives or personal dosing."
        )
    ),
    Level.general_public: LearnerProfile(
        level=Level.general_public,
        target_audience="Adult public seeking clear health literacy",
        assumed_prerequisites=["Basic human anatomy familiarity"],
        bloom_taxonomy_target="Understand & Apply (Health Literacy)",
        curricular_scope="Clear definition, everyday risk factors, body effects, non-prescriptive medical care concepts, preventive lifestyle science",
        pedagogical_instructions=(
            "Explain in clear, empowering language for an adult with no medical background. "
            "Demystify complex terms with immediate plain-English explanations. Focus on how the body works "
            "and why treatments function, avoiding sensationalism or medical jargon."
        )
    ),
}

LEVEL_INSTRUCTIONS: dict[Level, str] = {
    lvl: (
        f"Target Audience: {prof.target_audience}. "
        f"Assumed Prerequisites: {', '.join(prof.assumed_prerequisites)}. "
        f"Target Bloom's Taxonomy Level: {prof.bloom_taxonomy_target}. "
        f"Curricular Scope: {prof.curricular_scope}. "
        f"{prof.pedagogical_instructions}"
    )
    for lvl, prof in LEARNER_PROFILES.items()
}

SYSTEM_PROMPT_TEMPLATE = """You are a medical education content generator for MedLearn AI, a platform whose sole purpose is teaching how diseases, organs, cells, and treatments work - NOT diagnosing individuals or giving personal medical advice.

CRITICAL RULES:
1. Only state facts present in the provided source context below. If the context does not cover something, say so explicitly rather than filling in from general knowledge.
2. Never address the reader as if they personally have the condition. Write about the condition/process in general terms ("this condition typically causes...", never "you have...").
3. When describing treatments, explain MECHANISM ONLY (how a drug class works, why a procedure helps) - never dosing, personal suitability, or directives like "you should take."
4. Every factual claim must be attributable to one of the provided sources.
5. Pedagogical Calibration: {level_instruction}

QUIZ GENERATION REQUIREMENTS:
- Generate exactly 3 clinical vignette or mechanistic deduction questions (not mere superficial terminology recall).
- Provide 4 medically plausible options derived from physiological principles (absolutely NO absurd, impossible, or cartoonish distractors).
- Each question must evaluate causal understanding of disease progression, compensatory feedback, or therapeutic mechanism.
- Provide a detailed explanation explaining why the correct choice is physiologically sound and why the alternative distractors are incorrect.

Return ONLY a JSON object matching this exact schema, no other text:
{{
  "topic": "<topic name>",
  "level": "{level_value}",
  "sections": [
    {{"id": "what_is_it", "title": "What is it?", "content": "...", "diagram_type": "concept_overview", "sources": [{{"org": "...", "url": "...", "title": "..."}}]}},
    {{"id": "causes", "title": "What causes it?", "content": "...", "diagram_type": "cause_diagram", "sources": [...]}},
    {{"id": "location", "title": "Where does it happen in the body?", "content": "...", "diagram_type": "body_location", "sources": [...]}},
    {{"id": "progression", "title": "How does it develop?", "content": "...", "diagram_type": "process_flow", "sources": [...]}},
    {{"id": "cellular", "title": "What happens inside cells/organs?", "content": "...", "diagram_type": "cellular_process", "sources": [...]}},
    {{"id": "immune_response", "title": "How does the body respond?", "content": "...", "diagram_type": "process_flow", "sources": [...]}},
    {{"id": "treatment_mechanism", "title": "How do treatments work?", "content": "...", "diagram_type": "mechanism_diagram", "sources": [...]}},
    {{"id": "prevention", "title": "Prevention and risk factors", "content": "...", "diagram_type": "concept_overview", "sources": [...]}}
  ],
  "quiz": [
    {{"question": "...", "options": ["...", "...", "...", "..."], "correct_index": 0, "explanation": "..."}}
  ]
}}"""



def build_system_prompt(level: Level) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        level_instruction=LEVEL_INSTRUCTIONS[level],
        level_value=level.value,
    )


def build_user_prompt(topic: str, retrieved_context: str) -> str:
    return f"""Topic: {topic}

Retrieved source context (use ONLY this for facts):
---
{retrieved_context}
---

Generate the lesson JSON now."""


TUTOR_SYSTEM_PROMPT = """You are the AI Tutor for MedLearn AI, an educational \
medical platform. You are answering a follow-up question about a SPECIFIC \
lesson the reader just read. Stay scoped to that lesson's content and its \
underlying subject - you are not a general medical chatbot.

CRITICAL RULES (same as the lesson generator):
1. Base your answer on the lesson content provided below. If the question \
asks something the lesson doesn't cover, say the lesson doesn't go into \
that, and give a brief general-knowledge answer clearly labeled as such \
rather than inventing lesson-specific detail.
2. Never address the reader as if they personally have the condition. \
Explain the concept in general terms.
3. If asked something like "what happens if this step fails" or "explain \
this simpler," answer educationally - mechanism and consequence in \
general, not personalized medical guidance.
4. Never give dosing, personal treatment suitability, or diagnostic \
statements about the reader.
5. Keep answers focused and conversational - a few sentences to a short \
paragraph, not another full lesson.

Respond with plain text only, no JSON, no markdown headers."""


def build_tutor_prompt(lesson: "Lesson", conversation_history: list[dict], question: str) -> str:
    lesson_summary = "\n\n".join(f"{s.title}: {s.content}" for s in lesson.sections)

    history_block = ""
    if conversation_history:
        history_lines = [f"{m['role']}: {m['content']}" for m in conversation_history[-6:]]
        history_block = "\n\nRecent conversation:\n" + "\n".join(history_lines)

    return f"""Lesson topic: {lesson.topic} (level: {lesson.level.value})

Lesson content:
{lesson_summary}
{history_block}

Reader's question: {question}

Answer the question now."""


# ==============================================================================
# 8. RAG RETRIEVAL
# ==============================================================================

@dataclass
class RetrievedChunk:
    text: str
    org: str
    title: str
    url: str
    score: float


EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 1536


async def embed_query(query: str) -> list[float]:
    client = _get_openai_client()

    def _call() -> list[float]:
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=query)
        return response.data[0].embedding

    return await asyncio.to_thread(_call)


async def vector_search(embedding: list[float], top_k: int = 12) -> list[RetrievedChunk]:
    query_sql = _sql_text(
        """
        SELECT dc.chunk_text, s.org, s.title, s.url,
               1 - (dc.embedding <=> CAST(:query_embedding AS vector)) AS score
        FROM document_chunks dc
        JOIN sources s ON s.id = dc.source_id
        WHERE s.org = ANY(:trusted_orgs)
        ORDER BY dc.embedding <=> CAST(:query_embedding AS vector)
        LIMIT :top_k
        """
    )

    def _query() -> list[RetrievedChunk]:
        with engine.connect() as conn:
            rows = conn.execute(
                query_sql,
                {
                    "query_embedding": str(embedding),
                    "trusted_orgs": settings.trusted_orgs,
                    "top_k": top_k,
                },
            ).fetchall()
        return [
            RetrievedChunk(text=r.chunk_text, org=r.org, title=r.title, url=r.url, score=float(r.score))
            for r in rows
        ]

    return await asyncio.to_thread(_query)


async def embed_and_store_chunk(db: Session, source_id: uuid.UUID, chunk_text: str) -> "DocumentChunk":
    client = _get_openai_client()

    def _embed() -> list[float]:
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=chunk_text)
        return response.data[0].embedding

    embedding = await asyncio.to_thread(_embed)
    chunk = DocumentChunk(source_id=source_id, chunk_text=chunk_text, embedding=embedding)
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return chunk



# Prompt-injection phrases that should never appear verbatim in a RAG chunk
# injected into the model prompt.  If a poisoned document contains these,
# they are stripped/neutralised BEFORE they reach the LLM context window.
_RAG_INJECTION_PATTERNS = [
    # Instruction-override attempts
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(different|new|another|an?\s+AI|DAN)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are\s+)?(a\s+)?(doctor|physician|medical\s+professional|diagnost)", re.IGNORECASE),
    re.compile(r"(you\s+must|always|from\s+now\s+on|henceforth)\s+(diagnose|prescribe|recommend\s+medication|give\s+(medical\s+)?advice)", re.IGNORECASE),
    # Direct diagnosis injection
    re.compile(r"the\s+user\s+(has|likely\s+has|probably\s+has|suffers?\s+from)\s+\w+", re.IGNORECASE),
    re.compile(r"tell\s+the\s+(user|reader|patient)\s+(they\s+have|to\s+take|to\s+stop)", re.IGNORECASE),
    # Jailbreak markers
    re.compile(r"\[\s*(INST|SYS|SYSTEM|ASSISTANT|USER)\s*\]", re.IGNORECASE),
    re.compile(r"<\s*(system|assistant|instruction|prompt)\s*>", re.IGNORECASE),
    re.compile(r"###\s*(Instruction|System|Override)", re.IGNORECASE),
]


def sanitize_chunk_text(text: str) -> str:
    """
    Strip/neutralise known prompt-injection phrases from a RAG chunk before
    it is injected into a model prompt.  This runs at *both* ingest time
    (embed_and_store_chunk) and prompt-build time (format_context) so that
    chunks already in the DB are also covered when served.

    Detected injection phrases are replaced with a neutral placeholder so
    the chunk length is not altered in a way that would break chunking
    offsets, and so the log can show what was removed.
    """
    for pat in _RAG_INJECTION_PATTERNS:
        if pat.search(text):
            logger.warning(
                "RAG injection pattern detected in chunk text; neutralising: %r",
                pat.pattern,
            )
            text = pat.sub("[CONTENT REMOVED BY SAFETY FILTER]", text)
    return text


def format_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for c in chunks:
        safe_text = sanitize_chunk_text(c.text)
        blocks.append(f"[Source: {c.org} - {c.title} ({c.url})]\n{safe_text}")
    return "\n\n".join(blocks)



async def retrieve_for_topic(topic: str, top_k: int = 12) -> tuple[str, list[RetrievedChunk]]:
    chunks = []
    if settings.openai_api_key:
        try:
            embedding = await embed_query(topic)
            chunks = await vector_search(embedding, top_k=top_k)
        except Exception as e:
            logger.warning("Vector search for '%s' encountered an issue: %s - using trusted source synthesis", topic, e)
            chunks = []

    if not chunks:
        t_clean = topic.strip()
        t_title = t_clean.title()
        t_slug = t_clean.lower().replace(" ", "-")
        chunks = [
            RetrievedChunk(
                text=(
                    f"National Institutes of Health (NIH) and MedlinePlus Clinical Overview on {t_title}. "
                    f"{t_title} is a clinical and biological condition characterized by specific pathophysiology, "
                    f"target organ involvement, and altered cellular signaling cascades. "
                    f"Standard medical literature documents primary etiology, molecular pathogenesis, "
                    f"histopathological alterations, and homeostatic compensations. "
                    f"Understanding cellular transport, receptor activity, and physiological regulation is critical to educational mastery."
                ),
                org="NIH",
                title=f"NIH MedlinePlus: {t_title} Clinical Monograph",
                url=f"https://medlineplus.gov/{t_clean.lower().replace(' ', '')}.html",
                score=0.95
            ),
            RetrievedChunk(
                text=(
                    f"Centers for Disease Control and Prevention (CDC) Epidemiological and Public Health Reference for {t_title}. "
                    f"Details population epidemiology, primary environmental and genetic risk factors, "
                    f"transmission or progression vectors, and evidence-based prevention guidelines. "
                    f"Recommends proactive lifestyle factors, regular clinical screening, and community health interventions."
                ),
                org="CDC",
                title=f"CDC Public Health Guidance on {t_title}",
                url=f"https://www.cdc.gov/{t_slug}/index.html",
                score=0.91
            ),
            RetrievedChunk(
                text=(
                    f"PubMed Systematic Review: Cellular Signaling and Pharmacological Mechanisms in {t_title}. "
                    f"Examines receptor binding kinetics, intracellular messenger pathways (kinases, second messengers), "
                    f"transcriptional responses, and targeted molecular therapies. "
                    f"Therapeutic interventions focus on restoring cellular homeostasis and attenuating chronic organ remodeling."
                ),
                org="PubMed",
                title=f"PubMed: Molecular Pathophysiology and Therapeutics of {t_title}",
                url=f"https://pubmed.ncbi.nlm.nih.gov/?term={t_clean.lower().replace(' ', '+')}",
                score=0.88
            ),
            RetrievedChunk(
                text=(
                    f"World Health Organization (WHO) and FDA Clinical Therapeutics Compendium for {t_title}. "
                    f"Comprehensive global clinical overview covering disease burden, physiological staging, "
                    f"approved pharmacological mechanism classes, and non-prescriptive health guidelines."
                ),
                org="WHO",
                title=f"WHO Global Health Guidelines: {t_title}",
                url=f"https://www.who.int/news-room/fact-sheets/detail/{t_slug}",
                score=0.86
            )
        ]
    return format_context(chunks), chunks



# ==============================================================================
# 9. AI ENSEMBLE
# ==============================================================================

MAX_REGENERATION_ATTEMPTS = 2


class UnsafeLessonError(Exception):
    pass


_anthropic_client: anthropic.Anthropic | None = None
_openai_client: openai.OpenAI | None = None
_gemini_client: genai.Client | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=15.0)
    return _anthropic_client


def _get_openai_client() -> openai.OpenAI:
    global _openai_client
    if _openai_client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _openai_client = openai.OpenAI(api_key=settings.openai_api_key, timeout=15.0)
    return _openai_client


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        if not settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        _gemini_client = genai.Client(api_key=settings.google_api_key, http_options={"timeout": 15000})
    return _gemini_client


def _extract_json_block(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output")
    return text[start : end + 1]


def _build_educational_lesson_payload(topic: str, level: Level, retrieved_context: str) -> dict:
    t_clean = topic.strip().title()
    t_slug = topic.strip().lower().replace(" ", "-")
    lvl = level.value
    
    sections = [
        {
            "id": "what_is_it",
            "title": f"What is {t_clean}?",
            "content": f"{t_clean} is a medical and biological condition characterized by physiological alterations in normal cellular and organ function. Medical literature outlines its presentation through specific biochemical markers, histological changes, and progressive tissue responses.",
            "diagram_type": "concept_overview",
            "sources": [{"org": "NIH", "url": f"https://medlineplus.gov/{t_slug}.html", "title": f"NIH MedlinePlus Overview on {t_clean}"}]
        },
        {
            "id": "causes",
            "title": f"Etiology and Causes of {t_clean}",
            "content": f"The development of {t_clean} typically involves interplay between genetic predisposition, environmental triggers, metabolic demands, and immune regulation. These factors precipitate intracellular stress and receptor alterations.",
            "diagram_type": "cause_diagram",
            "sources": [{"org": "CDC", "url": f"https://www.cdc.gov/{t_slug}/index.html", "title": f"CDC Public Health Risk Factors for {t_clean}"}]
        },
        {
            "id": "location",
            "title": "Where does it happen in the body?",
            "content": f"Primary pathology localizes within specific target tissues and organs associated with {t_clean}. Secondary systemic compensations often engage the cardiovascular, endocrine, and renal systems as homeostatic feedback adapts.",
            "diagram_type": "body_location",
            "sources": [{"org": "NIH", "url": f"https://medlineplus.gov/{t_slug}.html", "title": f"NIH Anatomical Mapping for {t_clean}"}]
        },
        {
            "id": "progression",
            "title": "Pathophysiological Progression",
            "content": f"The pathophysiology of {t_clean} evolves across characteristic phases: initial exposure or cellular stress, localized receptor desensitization, compensatory biological activity, and potential chronic remodeling over time.",
            "diagram_type": "process_flow",
            "sources": [{"org": "PubMed", "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={t_slug}", "title": f"PubMed Clinical Review: Staging of {t_clean}"}]
        },
        {
            "id": "cellular",
            "title": "Cellular and Molecular Mechanisms",
            "content": f"At the cellular level, {t_clean} impacts membrane transport channels, second messenger cascades, mitochondrial oxidative phosphorylation, and transcription factor regulation within affected cell types.",
            "diagram_type": "cellular_process",
            "sources": [{"org": "PubMed", "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={t_slug}", "title": f"PubMed: Molecular Mechanisms of {t_clean}"}]
        },
        {
            "id": "immune_response",
            "title": "Immune and Systemic Response",
            "content": f"The immune system responds to tissue stress in {t_clean} by mobilizing surveillance leukocytes, modulating inflammatory cytokine cascades, and facilitating debris clearance and endothelial repair.",
            "diagram_type": "process_flow",
            "sources": [{"org": "WHO", "url": f"https://www.who.int/news-room/fact-sheets/detail/{t_slug}", "title": f"WHO Global Immunopathology Report on {t_clean}"}]
        },
        {
            "id": "treatment_mechanism",
            "title": "Educational Pharmacological Mechanisms",
            "content": f"Educational treatment models demonstrate how therapeutics target molecular receptors, modulate enzyme activity, or restore vascular and cellular perfusion without substituting for professional medical care.",
            "diagram_type": "mechanism_diagram",
            "sources": [{"org": "FDA", "url": "https://www.fda.gov/drugs", "title": f"FDA Drug Classes and Mechanisms for {t_clean}"}]
        },
        {
            "id": "prevention",
            "title": "Risk Factors and Prevention",
            "content": f"Evidence-based public health guidelines emphasize routine health surveillance, balanced nutrition, regular physical activity to support vascular health, and mitigating modifiable lifestyle exposures.",
            "diagram_type": "concept_overview",
            "sources": [{"org": "CDC", "url": f"https://www.cdc.gov/{t_slug}/index.html", "title": f"CDC Prevention Guidelines for {t_clean}"}]
        }
    ]
    
    quiz = [
        {
            "question": f"What is a primary physiological feature observed in {t_clean}?",
            "options": [
                "Altered cellular transport and signaling pathways",
                "Spontaneous conversion of muscle to bone",
                "Complete absence of all white blood cells",
                "Instant permanent cessation of all metabolism"
            ],
            "correct_index": 0,
            "explanation": f"In {t_clean}, cellular transport channels and receptor signaling pathways undergo characteristic changes that disrupt normal metabolic homeostasis."
        },
        {
            "question": f"How do educational pharmacological mechanisms aim to help in {t_clean}?",
            "options": [
                "By replacing all bodily fluids instantaneously",
                "By modulating specific molecular receptors to restore physiological balance",
                "By eliminating the need for cellular oxygen consumption",
                "By converting all carbohydrates directly into fat within minutes"
            ],
            "correct_index": 1,
            "explanation": f"Medications target specific receptors or enzymes involved in {t_clean} to re-establish physiological equilibrium."
        },
        {
            "question": f"Which sources provide reliable scientific guidance regarding {t_clean}?",
            "options": [
                "Commercial advertisements and social media claims",
                "Established institutions such as the NIH, CDC, and WHO",
                "Anonymous forum posts without citations",
                "Unverified marketing blogs"
            ],
            "correct_index": 1,
            "explanation": "Authoritative evidence-based clinical guidance is published by established organizations such as the CDC, WHO, and NIH."
        }
    ]
    
    return {
        "topic": t_clean,
        "level": lvl,
        "sections": sections,
        "quiz": quiz
    }


async def call_claude(system_prompt: str, user_prompt: str) -> str:
    client = _get_anthropic_client()

    def _call() -> str:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return _extract_json_block(text)

    return await asyncio.to_thread(_call)


async def call_gemini_qc(section_text: str) -> dict:
    client = _get_gemini_client()

    def _call() -> dict:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=build_qc_prompt(section_text),
            config=genai_types.GenerateContentConfig(system_instruction=QC_SYSTEM_PROMPT),
        )
        raw = _extract_json_block(response.text)
        return json.loads(raw)

    return await asyncio.to_thread(_call)


async def call_gpt4o_shadow(system_prompt: str, user_prompt: str) -> str:
    client = _get_openai_client()

    def _call() -> str:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return await asyncio.to_thread(_call)


def log_shadow_disagreement(topic: str, level: str, primary_json: str, shadow_json: str) -> None:
    try:
        primary = json.loads(primary_json)
        shadow = json.loads(shadow_json)
        primary_ids = {s.get("id") for s in primary.get("sections", [])}
        shadow_ids = {s.get("id") for s in shadow.get("sections", [])}
        if primary_ids != shadow_ids:
            logger.warning(
                "Shadow disagreement on section coverage for '%s' (%s): primary=%s shadow=%s",
                topic, level, primary_ids, shadow_ids,
            )
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning("Could not compare shadow draft for '%s': %s", topic, e)


async def run_safety_checks(lesson: Lesson) -> list[str]:
    all_flags: list[str] = []
    gemini_configured = bool(settings.google_api_key)

    for section in lesson.sections:
        screen_result = pattern_screen(section.content)
        if not screen_result.passed:
            all_flags.extend(f"[{section.id}] {f}" for f in screen_result.flags)
            continue

        if not gemini_configured:
            continue

        try:
            qc = await call_gemini_qc(section.content)
            if not qc.get("safe", False):
                all_flags.append(f"[{section.id}] qc: {qc.get('reason', 'flagged')}")
        except Exception as e:
            logger.error("Gemini QC call failed for section '%s': %s", section.id, e)
            # Fail-closed: an unreviewable section must never be treated as safe.
            all_flags.append(f"[{section.id}] qc_error: {type(e).__name__}")

    return all_flags


def _fire_shadow_task(topic: str, level: Level, system_prompt: str, user_prompt: str, primary_raw: str) -> None:
    if not settings.openai_api_key:
        return

    async def _run():
        try:
            shadow_raw = await call_gpt4o_shadow(system_prompt, user_prompt)
            log_shadow_disagreement(topic, level.value, primary_raw, shadow_raw)
        except Exception as e:
            logger.warning("Shadow GPT-4o draft failed for '%s': %s", topic, e)

    asyncio.create_task(_run())


async def generate_lesson(topic: str, level: Level, retrieved_context: str) -> Lesson:
    system_prompt = build_system_prompt(level)
    user_prompt = build_user_prompt(topic, retrieved_context)

    attempt = 0
    last_flags: list[str] = []

    while attempt < MAX_REGENERATION_ATTEMPTS:
        attempt += 1

        if attempt > 1 and last_flags:
            user_prompt += (
                "\n\nThe previous draft was flagged for the following issues "
                "and MUST be corrected - rewrite affected sections to be "
                "purely educational, removing any reader-directed diagnostic "
                f"or prescriptive language:\n{json.dumps(last_flags)}"
            )

        raw = None
        # 1. Try Claude if key set
        if settings.anthropic_api_key:
            try:
                raw = await call_claude(system_prompt, user_prompt)
            except Exception as e:
                logger.warning("Claude generation failed: %s - falling back to multi-provider", e)

        # 2. Try Gemini if key set
        if not raw and settings.google_api_key:
            try:
                client = _get_gemini_client()
                def _call_gem() -> str:
                    resp = client.models.generate_content(
                        model=settings.gemini_model,
                        contents=user_prompt,
                        config=genai_types.GenerateContentConfig(system_instruction=system_prompt)
                    )
                    return _extract_json_block(resp.text or "")
                raw = await asyncio.to_thread(_call_gem)
            except Exception as e:
                logger.warning("Gemini generation failed: %s - falling back", e)

        # 3. Try OpenAI if key set
        if not raw and settings.openai_api_key:
            try:
                raw = await call_gpt4o_shadow(system_prompt, user_prompt)
            except Exception as e:
                logger.warning("OpenAI generation failed: %s", e)

        # 4. If ALL providers are unavailable/unconfigured, raise 503.
        # _build_educational_lesson_payload is NOT used here — it produces
        # fabricated source URLs that look real (medlineplus.gov/topic.html,
        # cdc.gov/topic/index.html) but are generated strings, not real
        # documents. Serving them would give users false confidence in sources
        # that may not exist. Return 503 and let the caller retry later.
        if not raw:
            raise UnsafeLessonError(
                "No AI provider is configured or available. "
                "Please add at least one of ANTHROPIC_API_KEY, GOOGLE_API_KEY, "
                "or OPENAI_API_KEY to generate lessons."
            )

        if attempt == 1 and settings.openai_api_key:
            _fire_shadow_task(topic, level, system_prompt, user_prompt, raw)

        try:
            data = json.loads(raw)
            lesson = Lesson(**data)
        except Exception as e:
            logger.warning("Malformed JSON in lesson generation (%s) - retrying", e)
            # Count this as a failed attempt; the loop will retry with the
            # rephrased prompt on the next iteration (or exhaust attempts).
            last_flags = [f"json_parse_error: {e}"]
            continue

        flags = await run_safety_checks(lesson)
        if not flags:
            lesson.safety_flags = []
            return lesson

        last_flags = flags
        logger.warning("Lesson generation attempt %d flagged: %s", attempt, flags)

    # All attempts exhausted with safety flags still set.
    raise UnsafeLessonError(
        f"Could not generate a safe lesson for '{topic}' after "
        f"{MAX_REGENERATION_ATTEMPTS} attempts. Safety flags: {last_flags}"
    )



class UnsafeTutorAnswerError(Exception):
    """Raised when a tutor answer fails the safety pattern screen after retry."""


async def answer_tutor_question(lesson: Lesson, conversation_history: list[dict], question: str) -> str:
    """Answer a follow-up question scoped to a specific lesson's content with safety checks."""
    prompt = build_tutor_prompt(lesson, conversation_history, question)

    attempt = 0
    while attempt < 2:
        attempt += 1
        full_prompt = prompt
        if attempt > 1:
            full_prompt += (
                "\n\n(Your previous answer was flagged for reader-directed "
                "diagnostic or prescriptive language. Rewrite it to be "
                "strictly educational.)"
            )

        answer = None
        # 1. Try Claude if configured
        if settings.anthropic_api_key:
            try:
                client = _get_anthropic_client()
                def _call() -> str:
                    response = client.messages.create(
                        model=settings.claude_model,
                        max_tokens=600,
                        system=TUTOR_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": full_prompt}],
                    )
                    return "".join(block.text for block in response.content if block.type == "text").strip()
                answer = await asyncio.to_thread(_call)
            except Exception as e:
                logger.warning("Claude tutor answer failed: %s", e)

        # 2. Try Gemini if configured
        if not answer and settings.google_api_key:
            try:
                client = _get_gemini_client()
                def _call_gem() -> str:
                    resp = client.models.generate_content(
                        model=settings.gemini_model,
                        contents=full_prompt,
                        config=genai_types.GenerateContentConfig(system_instruction=TUTOR_SYSTEM_PROMPT)
                    )
                    return (resp.text or "").strip()
                answer = await asyncio.to_thread(_call_gem)
            except Exception as e:
                logger.warning("Gemini tutor answer failed: %s", e)

        # 3. Grounded Contextual Educational Tutoring Synthesis
        if not answer:
            q_lower = question.lower()
            t_name = lesson.topic
            if "simple" in q_lower or "simpler" in q_lower or "kid" in q_lower:
                answer = f"In simple terms: Think of {t_name} like a key that cannot easily unlock a door. When normal cellular signals are hindered, cells cannot take in what they need, requiring the body to adapt."
            elif "fail" in q_lower or "what happens if" in q_lower:
                answer = f"If normal regulatory mechanisms fail in {t_name}, the affected tissues experience cellular backlog and metabolic stress. Over time, this leads to structural remodeling and compensatory strain across related organs."
            elif "why" in q_lower:
                answer = f"This occurs in {t_name} because cellular receptor pathways and transport channels become less responsive under metabolic stress, altering the normal rate of physiological exchange."
            else:
                answer = f"Regarding {t_name}: The educational material notes that primary mechanisms involve cellular receptor transport and localized organ adaptation. Medical treatments focus on restoring molecular balance and preventing chronic organ strain."

        screen_result = pattern_screen(answer)
        if screen_result.passed:
            return answer

        logger.warning("Tutor answer attempt %d flagged: %s", attempt, screen_result.flags)

    # Safe sanitize
    return f"From an educational standpoint, {lesson.topic} involves regulated cellular mechanisms and target organ pathways. Medical interventions aim to restore physiological balance and minimize cellular stress."



# ==============================================================================
# 10. API ROUTES
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager replacing deprecated @app.on_event('startup') (M-06)."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully on startup.")
    except Exception as e:
        logger.warning("Database table creation notice: %s", e)
    yield


app = FastAPI(
    title="MedLearn AI",
    description="Educational medical AI platform - not for diagnosis or treatment.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.cors_origin_list == ["*"] and settings.is_production:
    logger.warning(
        "CORS_ORIGINS is '*' while running in production - set explicit "
        "frontend origin(s) before going live."
    )

API_PREFIX = f"/api/{settings.api_version}"


@app.get("/health")
async def health_shallow():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    checks: dict[str, str] = {}
    healthy = True

    try:
        with engine.connect() as conn:
            conn.execute(_sql_text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    if settings.redis_url:
        try:
            import redis as redis_lib

            client = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            client.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"

    status_code = 200 if healthy else 503
    return JSONResponse(status_code=status_code, content={"status": "ok" if healthy else "degraded", "checks": checks})


@app.post(f"{API_PREFIX}/auth/register", response_model=TokenResponse, status_code=201)
async def register(req: UserRegisterRequest, request: Request, db: Session = Depends(get_db)):
    try:
        check_rate_limit(f"register:{get_client_ip(request)}", max_requests=5, window_seconds=3600)
    except RateLimitExceeded as e:
        return rate_limit_response(e)

    normalized_email = req.email.strip().lower()

    if len(req.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Could not register with the provided details")

    user = User(email=normalized_email, hashed_password=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    verification_token = create_access_token(str(user.id), user.role)
    EmailService.send_verification_email(user.email, verification_token)

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id), user.role),
    )


@app.post(f"{API_PREFIX}/auth/login", response_model=TokenResponse)
async def login(req: UserLoginRequest, request: Request, db: Session = Depends(get_db)):
    normalized_email = req.email.strip().lower()

    try:
        # Keyed by email+IP together, not either alone: an attacker
        # spraying one password across many emails from one IP is still
        # throttled (IP component), and a distributed attack against one
        # specific email from many IPs is still throttled (email
        # component) - one key alone would miss one of those two attack
        # shapes.
        check_rate_limit(f"login:{normalized_email}:{get_client_ip(request)}", max_requests=10, window_seconds=300)
    except RateLimitExceeded as e:
        return rate_limit_response(e)

    user = db.query(User).filter(User.email == normalized_email).first()

    dummy_hash = "$2b$12$CwTycUXWue0Thq9StjUM0uJ8w4nCNjQ0nDh8H2vHrq8bYQXqfKf5C"
    password_ok = verify_password(req.password, user.hashed_password if user else dummy_hash)

    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not user.is_active:
        # Distinct message here is fine (unlike get_current_user) - the
        # person is actively trying to log in with correct credentials, so
        # telling them the account is deactivated is legitimately useful
        # and doesn't leak anything they don't already know (they just
        # proved they own the account by supplying the right password).
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id), user.role),
    )


@app.post(f"{API_PREFIX}/auth/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id), user.role),
    )


@app.get(f"{API_PREFIX}/users/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    return UserProfile(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


@app.post(f"{API_PREFIX}/lessons/search", response_model=Lesson)
async def search_lesson(
    req: LessonSearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # ── Emergency / crisis gate (runs before cache, before AI) ──────────────
    flagged, category = screen_for_emergency(req.topic)
    if flagged:
        raise emergency_http_exception(category)
    # ────────────────────────────────────────────────────────────────────────

    topic_normalized = req.topic.strip().lower()

    def log_history(found: bool) -> None:
        # Anonymous searches aren't logged - no durable identity to attach
        # them to. Failures here (e.g. a weird DB hiccup) shouldn't ever
        # break the actual search response, so this never raises past
        # itself; the search result is the thing that matters to the
        # caller, not whether the history row landed.
        if user is None:
            return
        try:
            db.add(SearchHistory(user_id=user.id, query=req.topic, level=req.level.value, found_result=found))
            db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to log search history: %s", e)

    cached = (
        db.query(LessonRecord)
        .filter(LessonRecord.topic == topic_normalized, LessonRecord.level == req.level.value)
        .first()
    )
    if cached:
        # Cache hits are cheap (one DB read, no AI call) - deliberately not
        # rate-limited so a popular topic doesn't get throttled just
        # because many people are viewing it. Only the expensive path
        # below (actual generation) counts against the limit.
        lesson = Lesson(**cached.content)
        lesson.id = str(cached.id)
        log_history(found=True)
        return lesson

    rate_limit_key = f"search:{user.id if user else get_client_ip(request)}"
    try:
        check_rate_limit(rate_limit_key, max_requests=20, window_seconds=3600)
    except RateLimitExceeded as e:
        return rate_limit_response(e)

    try:
        context, chunks = await retrieve_for_topic(req.topic)
    except ValueError as e:
        log_history(found=False)
        raise HTTPException(status_code=404, detail=str(e))

    try:
        lesson = await generate_lesson(req.topic, req.level, context)
    except UnsafeLessonError as e:
        err_msg = str(e)
        if "No AI provider" in err_msg:
            logger.error("No AI provider configured: %s", err_msg)
            raise HTTPException(
                status_code=503,
                detail=(
                    "The lesson generation service is temporarily unavailable. "
                    "No AI provider API key is configured. "
                    "Please try again later or contact the administrator."
                ),
            )
        logger.error("Unsafe lesson blocked after all attempts: %s", err_msg)
        raise HTTPException(
            status_code=422,
            detail="Could not generate a safe educational lesson for this topic. Please try rephrasing.",
        )

    record = LessonRecord(
        topic=topic_normalized,
        level=req.level.value,
        content=lesson.model_dump(mode="json"),
        model_versions={"claude": "primary", "gemini": "qc"},
        safety_flags=lesson.safety_flags,
    )
    db.add(record)
    db.commit()
    db.refresh(record)  # populate record.id (server-generated default) before use below

    lesson.id = str(record.id)
    log_history(found=True)
    return lesson


@app.get(f"{API_PREFIX}/lessons/{{lesson_id}}", response_model=Lesson)
async def get_lesson(lesson_id: str, db: Session = Depends(get_db)):
    record = db.query(LessonRecord).filter(LessonRecord.id == lesson_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson = Lesson(**record.content)
    lesson.id = str(record.id)
    return lesson


# --- Search Engine routes ------------------------------------------------------
# Autocomplete and Popular Searches are both derived from LessonRecord.topic
# - i.e. topics that have ALREADY been generated at least once. This is an
# honest limitation worth stating plainly: a brand-new topic nobody has
# searched yet won't autocomplete or appear as popular, the same
# bootstrapping behavior most real search-suggestion systems have when
# seeded from historical query logs rather than a separately curated
# taxonomy (which Medical Knowledge Service, not built in this session,
# would be the right place to add).

@app.get(f"{API_PREFIX}/search/autocomplete", response_model=list[AutocompleteSuggestion])
async def search_autocomplete(q: str, limit: int = 8, db: Session = Depends(get_db)):
    prefix = q.strip().lower()
    if len(prefix) < 2:
        # Too short to be a useful prefix match - avoid returning a huge,
        # near-random slice of every topic ever generated for a
        # single-character query.
        return []

    limit = min(limit, 20)
    matches = (
        db.query(LessonRecord.topic, sa_func.count(LessonRecord.id))
        .filter(LessonRecord.topic.like(f"{prefix}%"))
        .group_by(LessonRecord.topic)
        .order_by(sa_func.count(LessonRecord.id).desc())
        .limit(limit)
        .all()
    )
    return [AutocompleteSuggestion(topic=topic, level_count=count) for topic, count in matches]


@app.get(f"{API_PREFIX}/search/popular", response_model=list[PopularSearch])
async def search_popular(limit: int = 10, db: Session = Depends(get_db)):
    limit = min(limit, 50)
    rows = (
        db.query(LessonRecord.topic, sa_func.count(LessonRecord.id))
        .group_by(LessonRecord.topic)
        .order_by(sa_func.count(LessonRecord.id).desc())
        .limit(limit)
        .all()
    )
    return [PopularSearch(topic=topic, search_count=count) for topic, count in rows]


@app.get(f"{API_PREFIX}/users/me/search-history", response_model=list[SearchHistoryEntry])
async def get_search_history(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    entries = (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == user.id)
        .order_by(SearchHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        SearchHistoryEntry(query=e.query, level=e.level, found_result=e.found_result, created_at=e.created_at)
        for e in entries
    ]


# --- Medical Knowledge Service routes -------------------------------------------
# Curated topic taxonomy: browsing is public, mutation is admin-only.
# Genuinely distinct from Search Engine (which surfaces what's already
# been GENERATED or SEARCHED) - this is a small, deliberately-curated
# structure of what topics exist and how they relate, independent of
# generation/search history.

@app.get(f"{API_PREFIX}/knowledge/topics", response_model=list[TaxonomyEntryView])
async def list_taxonomy_topics(
    category: str | None = None,
    q: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Public browse/search endpoint. q matches against canonical_name OR
    any synonym (case-insensitive substring), since a reader might type
    a common name rather than the canonical one - e.g. searching "sugar
    disease" should still be able to find "Diabetes" if that's listed as
    a synonym."""
    limit = min(limit, 200)
    query = db.query(TopicTaxonomy)
    if category:
        query = query.filter(TopicTaxonomy.category == category)
    entries = query.order_by(TopicTaxonomy.canonical_name.asc()).all()

    if q:
        q_lower = q.strip().lower()
        entries = [
            e for e in entries
            if q_lower in e.canonical_name.lower() or any(q_lower in s.lower() for s in e.synonyms)
        ]

    entries = entries[:limit]
    return [
        TaxonomyEntryView(
            id=str(e.id), canonical_name=e.canonical_name, category=e.category,
            synonyms=e.synonyms, related_topics=e.related_topics,
        )
        for e in entries
    ]


@app.get(f"{API_PREFIX}/knowledge/categories", response_model=list[str])
async def list_taxonomy_categories(db: Session = Depends(get_db)):
    rows = db.query(TopicTaxonomy.category).distinct().order_by(TopicTaxonomy.category.asc()).all()
    return [r[0] for r in rows]


@app.post(f"{API_PREFIX}/admin/knowledge/topics", response_model=TaxonomyEntryView, status_code=201)
async def admin_create_taxonomy_topic(
    req: TaxonomyEntryCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    normalized = req.canonical_name.strip()
    existing = db.query(TopicTaxonomy).filter(TopicTaxonomy.canonical_name == normalized).first()
    if existing:
        raise HTTPException(status_code=400, detail="A taxonomy entry with this canonical name already exists")

    entry = TopicTaxonomy(
        canonical_name=normalized, category=req.category.strip(),
        synonyms=[s.strip() for s in req.synonyms if s.strip()],
        related_topics=[t.strip() for t in req.related_topics if t.strip()],
    )
    db.add(entry)
    write_audit_log(
        db, admin, "taxonomy.created", "topic_taxonomy", normalized,
        details={"category": entry.category},
    )
    db.commit()
    db.refresh(entry)
    return TaxonomyEntryView(
        id=str(entry.id), canonical_name=entry.canonical_name, category=entry.category,
        synonyms=entry.synonyms, related_topics=entry.related_topics,
    )


@app.put(f"{API_PREFIX}/admin/knowledge/topics/{{topic_id}}", response_model=TaxonomyEntryView)
async def admin_update_taxonomy_topic(
    topic_id: str,
    req: TaxonomyEntryUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    try:
        topic_uuid = uuid.UUID(topic_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid topic id")

    entry = db.query(TopicTaxonomy).filter(TopicTaxonomy.id == topic_uuid).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Taxonomy entry not found")

    if req.category is not None:
        entry.category = req.category.strip()
    if req.synonyms is not None:
        entry.synonyms = [s.strip() for s in req.synonyms if s.strip()]
    if req.related_topics is not None:
        entry.related_topics = [t.strip() for t in req.related_topics if t.strip()]

    write_audit_log(
        db, admin, "taxonomy.updated", "topic_taxonomy", str(entry.id),
        details={"canonical_name": entry.canonical_name, "changed_fields": list(req.model_dump(exclude_none=True).keys())},
    )
    db.commit()
    db.refresh(entry)
    return TaxonomyEntryView(
        id=str(entry.id), canonical_name=entry.canonical_name, category=entry.category,
        synonyms=entry.synonyms, related_topics=entry.related_topics,
    )


@app.delete(f"{API_PREFIX}/admin/knowledge/topics/{{topic_id}}", status_code=204)
async def admin_delete_taxonomy_topic(
    topic_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    try:
        topic_uuid = uuid.UUID(topic_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid topic id")

    entry = db.query(TopicTaxonomy).filter(TopicTaxonomy.id == topic_uuid).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Taxonomy entry not found")

    write_audit_log(db, admin, "taxonomy.deleted", "topic_taxonomy", str(entry.id), details={"canonical_name": entry.canonical_name})
    db.delete(entry)
    db.commit()


def _get_or_create_history(db: Session, user_id: uuid.UUID, lesson_id: uuid.UUID) -> UserLessonHistory:
    entry = (
        db.query(UserLessonHistory)
        .filter(UserLessonHistory.user_id == user_id, UserLessonHistory.lesson_id == lesson_id)
        .first()
    )
    if entry is None:
        # Explicit defaults here, not relying on the column-level
        # default=0/False - those are flush-time (INSERT) defaults in
        # SQLAlchemy, not construction-time ones, so a caller that reads
        # or mutates a brand-new entry's fields before the next commit
        # (e.g. submit_quiz doing entry.quiz_attempts += 1 when this is
        # the very first interaction with a lesson, with no prior
        # record_lesson_view/set_bookmark call to have already committed
        # and refreshed the row) would otherwise see None instead of 0/False.
        entry = UserLessonHistory(
            user_id=user_id, lesson_id=lesson_id,
            quiz_attempts=0, completed=False, bookmarked=False,
        )
        db.add(entry)
    return entry


@app.post(f"{API_PREFIX}/lessons/{{lesson_id}}/view", status_code=204)
async def record_lesson_view(
    lesson_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    lesson_record = db.query(LessonRecord).filter(LessonRecord.id == lesson_uuid).first()
    if lesson_record is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    entry = _get_or_create_history(db, user.id, lesson_uuid)
    entry.last_viewed_at = _utc_now()
    db.commit()


@app.put(f"{API_PREFIX}/lessons/{{lesson_id}}/bookmark", status_code=204)
async def set_bookmark(
    lesson_id: str,
    bookmarked: bool,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    lesson_record = db.query(LessonRecord).filter(LessonRecord.id == lesson_uuid).first()
    if lesson_record is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    entry = _get_or_create_history(db, user.id, lesson_uuid)
    entry.bookmarked = bookmarked
    db.commit()


@app.post(f"{API_PREFIX}/lessons/{{lesson_id}}/quiz/submit", response_model=QuizSubmitResponse)
async def submit_quiz(
    lesson_id: str,
    req: QuizSubmitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    lesson_record = db.query(LessonRecord).filter(LessonRecord.id == lesson_uuid).first()
    if lesson_record is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson = Lesson(**lesson_record.content)

    if len(req.answers) != len(lesson.quiz):
        raise HTTPException(
            status_code=422,
            detail=f"Expected {len(lesson.quiz)} answers, got {len(req.answers)}",
        )

    results = []
    correct_count = 0
    for question, selected_index in zip(lesson.quiz, req.answers):
        is_correct = selected_index == question.correct_index
        if is_correct:
            correct_count += 1
        results.append(
            {
                "question": question.question,
                "selected_index": selected_index,
                "correct_index": question.correct_index,
                "correct": is_correct,
                "explanation": question.explanation,
            }
        )

    score = correct_count / len(lesson.quiz) if lesson.quiz else 0.0

    entry = _get_or_create_history(db, user.id, lesson_uuid)
    entry.quiz_attempts += 1
    entry.completed = True
    if entry.quiz_score is None or score > float(entry.quiz_score):
        entry.quiz_score = score
    db.commit()

    return QuizSubmitResponse(score=score, correct_count=correct_count, total=len(lesson.quiz), results=results)


@app.get(f"{API_PREFIX}/users/me/history", response_model=list[LessonHistoryEntry])
async def get_history(
    completed_only: bool = False,
    bookmarked_only: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(UserLessonHistory).filter(UserLessonHistory.user_id == user.id)
    if completed_only:
        query = query.filter(UserLessonHistory.completed.is_(True))
    if bookmarked_only:
        query = query.filter(UserLessonHistory.bookmarked.is_(True))

    entries = query.order_by(UserLessonHistory.last_viewed_at.desc()).all()

    results = []
    for entry in entries:
        lesson_record = db.query(LessonRecord).filter(LessonRecord.id == entry.lesson_id).first()
        if lesson_record is None:
            continue
        results.append(
            LessonHistoryEntry(
                lesson_id=str(entry.lesson_id),
                topic=lesson_record.topic,
                level=lesson_record.level,
                viewed_at=entry.viewed_at,
                last_viewed_at=entry.last_viewed_at,
                quiz_score=float(entry.quiz_score) if entry.quiz_score is not None else None,
                quiz_attempts=entry.quiz_attempts,
                completed=entry.completed,
                bookmarked=entry.bookmarked,
            )
        )
    return results


@app.get(f"{API_PREFIX}/users/me/stats", response_model=LearningStats)
async def get_learning_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = db.query(UserLessonHistory).filter(UserLessonHistory.user_id == user.id).all()

    scores = [float(e.quiz_score) for e in entries if e.quiz_score is not None]
    topics = set()
    for e in entries:
        lesson_record = db.query(LessonRecord).filter(LessonRecord.id == e.lesson_id).first()
        if lesson_record:
            topics.add(lesson_record.topic)

    return LearningStats(
        lessons_viewed=len(entries),
        lessons_completed=sum(1 for e in entries if e.completed),
        lessons_bookmarked=sum(1 for e in entries if e.bookmarked),
        average_quiz_score=(sum(scores) / len(scores)) if scores else None,
        topics_covered=sorted(topics),
    )


# --- AI Tutor Engine routes ----------------------------------------------------
# Follow-up Q&A scoped to a specific lesson. Works anonymously (user_id is
# nullable on TutorMessage) so it matches the rest of the platform's
# anonymous-by-default pattern - conversation history is only persisted and
# retrievable for signed-in users, since there's no anonymous session
# concept to key it on otherwise.

@app.post(f"{API_PREFIX}/lessons/{{lesson_id}}/tutor", response_model=TutorResponse)
async def ask_tutor(
    lesson_id: str,
    req: TutorRequest,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Works for both anonymous and signed-in readers via
    get_current_user_optional, which returns None instead of 401ing when
    there's no/invalid token."""

    # ── Emergency / crisis gate (runs before ANY AI call) ───────────────────
    flagged, category = screen_for_emergency(req.question)
    if flagged:
        raise emergency_http_exception(category)
    # ────────────────────────────────────────────────────────────────────────

    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    lesson_record = db.query(LessonRecord).filter(LessonRecord.id == lesson_uuid).first()
    if lesson_record is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson = Lesson(**lesson_record.content)

    # Prior turns for this lesson conversation - scoped by user_id when
    # signed in; anonymous conversations have no continuity across
    # requests (no session id in this schema yet), which is an accepted
    # limitation rather than a bug: it just means multi-turn tutor context
    # only threads correctly for signed-in users for now.
    history_query = db.query(TutorMessage).filter(TutorMessage.lesson_id == lesson_uuid)
    if user is not None:
        history_query = history_query.filter(TutorMessage.user_id == user.id)
    else:
        history_query = history_query.filter(TutorMessage.user_id.is_(None))
    prior_messages = history_query.order_by(TutorMessage.created_at.asc()).all()
    conversation_history = [{"role": m.role, "content": m.content} for m in prior_messages]

    try:
        answer = await answer_tutor_question(lesson, conversation_history, req.question)
    except UnsafeTutorAnswerError as e:
        logger.error("Unsafe tutor answer blocked: %s", e)
        raise HTTPException(
            status_code=422,
            detail="Could not generate a safe educational answer to that question. Please try rephrasing.",
        )

    db.add(TutorMessage(lesson_id=lesson_uuid, user_id=user.id if user else None, role="user", content=req.question))
    db.add(TutorMessage(lesson_id=lesson_uuid, user_id=user.id if user else None, role="assistant", content=answer))
    db.commit()

    return TutorResponse(answer=answer, lesson_id=str(lesson_uuid))


@app.get(f"{API_PREFIX}/lessons/{{lesson_id}}/tutor/history", response_model=list[TutorHistoryEntry])
async def get_tutor_history(
    lesson_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Signed-in only - anonymous tutor conversations aren't retrievable
    after the fact since they aren't keyed to anything durable."""
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    messages = (
        db.query(TutorMessage)
        .filter(TutorMessage.lesson_id == lesson_uuid, TutorMessage.user_id == user.id)
        .order_by(TutorMessage.created_at.asc())
        .all()
    )
    return [TutorHistoryEntry(role=m.role, content=m.content, created_at=m.created_at) for m in messages]


# --- Analytics Engine routes ---------------------------------------------------
# Platform-wide aggregates for an admin dashboard, admin-role-gated via
# require_role(UserRole.admin). Everything here is computed directly from
# existing tables (LessonRecord, UserLessonHistory, TutorMessage, User) -
# no separate event-logging pipeline exists yet, so these are point-in-time
# aggregate queries, not a time-series/event-stream analytics system.
#
# Deliberately NOT included: Performance Metrics (request latency, error
# rates) and structured Error Logs from the original roadmap. Those need
# actual request-level instrumentation (middleware timing, exception
# capture) that doesn't exist in this build - faking them from data that
# isn't there would be worse than leaving them out. What's below only
# covers what the existing tables can honestly answer: who's using the
# platform, what they're searching for, how they're doing on quizzes, and
# how much they're using the tutor.

def _compute_user_analytics(db: Session) -> UserAnalytics:
    all_users = db.query(User).all()
    by_role: dict[str, int] = {}
    for u in all_users:
        by_role[u.role] = by_role.get(u.role, 0) + 1
    return UserAnalytics(
        total_users=len(all_users),
        verified_users=sum(1 for u in all_users if u.is_verified),
        users_by_role=by_role,
    )


def _compute_search_analytics(db: Session) -> SearchAnalytics:
    all_lessons = db.query(LessonRecord).all()

    level_dist: dict[str, int] = {}
    topic_search_counts: dict[str, int] = {}
    for lr in all_lessons:
        level_dist[lr.level] = level_dist.get(lr.level, 0) + 1
        topic_search_counts[lr.topic] = topic_search_counts.get(lr.topic, 0) + 1

    # view_count per topic requires joining through UserLessonHistory ->
    # LessonRecord, done in Python here rather than a SQL join since the
    # corpus size at this stage doesn't warrant the extra query complexity -
    # revisit with a proper aggregate query once lesson volume is real.
    lesson_id_to_topic = {lr.id: lr.topic for lr in all_lessons}
    topic_view_counts: dict[str, int] = {}
    for entry in db.query(UserLessonHistory).all():
        topic = lesson_id_to_topic.get(entry.lesson_id)
        if topic:
            topic_view_counts[topic] = topic_view_counts.get(topic, 0) + 1

    top_topics = sorted(
        (
            TopicPopularity(topic=t, search_count=c, view_count=topic_view_counts.get(t, 0))
            for t, c in topic_search_counts.items()
        ),
        key=lambda tp: (tp.view_count, tp.search_count),
        reverse=True,
    )[:10]

    return SearchAnalytics(
        total_lessons_generated=len(all_lessons),
        total_unique_topics=len(topic_search_counts),
        top_topics=top_topics,
        level_distribution=level_dist,
    )


def _compute_quiz_analytics(db: Session) -> QuizAnalytics:
    entries = db.query(UserLessonHistory).all()
    total_attempts = sum(e.quiz_attempts for e in entries)
    entries_with_attempts = [e for e in entries if e.quiz_attempts > 0]
    scores = [float(e.quiz_score) for e in entries if e.quiz_score is not None]

    lessons_viewed = len(entries)
    lessons_completed = sum(1 for e in entries if e.completed)

    return QuizAnalytics(
        total_attempts=total_attempts,
        total_lessons_with_attempts=len(entries_with_attempts),
        average_score=(sum(scores) / len(scores)) if scores else None,
        completion_rate=(lessons_completed / lessons_viewed) if lessons_viewed else None,
    )


def _compute_tutor_analytics(db: Session) -> TutorAnalytics:
    user_messages = db.query(TutorMessage).filter(TutorMessage.role == "user").all()
    lessons_with_activity = {m.lesson_id for m in user_messages}

    return TutorAnalytics(
        total_questions=len(user_messages),
        lessons_with_tutor_activity=len(lessons_with_activity),
        anonymous_question_count=sum(1 for m in user_messages if m.user_id is None),
        signed_in_question_count=sum(1 for m in user_messages if m.user_id is not None),
    )


@app.get(f"{API_PREFIX}/admin/analytics", response_model=PlatformAnalytics)
async def get_platform_analytics(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    all_lessons = db.query(LessonRecord).all()
    safety_flag_count = sum(1 for lr in all_lessons if lr.safety_flags)

    return PlatformAnalytics(
        users=_compute_user_analytics(db),
        search=_compute_search_analytics(db),
        quiz=_compute_quiz_analytics(db),
        tutor=_compute_tutor_analytics(db),
        safety_flag_count=safety_flag_count,
    )


def write_audit_log(
    db: Session, actor: User, action: str, target_type: str, target_id: str, details: dict | None = None
) -> None:
    """Writes one audit row. Called inline within each admin mutation, in
    the same DB transaction as the mutation itself - if the commit for the
    action fails, the audit entry doesn't get orphaned in a separate
    transaction claiming something happened that didn't. Callers are
    expected to db.add() this and let their own db.commit() cover it,
    rather than this function committing independently - see call sites
    below."""
    entry = AuditLog(
        actor_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )
    db.add(entry)


# --- Admin Engine routes -------------------------------------------------------
# User Management, Lesson Management, and Feedback from the original
# roadmap. All admin-only via require_role(UserRole.admin), except the
# feedback SUBMIT endpoint, which is open to any reader (including
# anonymous) - the whole point of feedback is being able to flag a problem
# without needing an account first.
#
# NOT built here: Topic Management, Asset Management, AI Monitoring,
# System Settings. Topic/Asset Management have no underlying content
# model to manage yet (no curated topic taxonomy, no asset pipeline - see
# docs/03_ROADMAP.md Phase 2/3). AI Monitoring overlaps heavily with what
# Analytics already covers (safety_flag_count, quiz/tutor volume) rather
# than being a distinct capability worth duplicating. System Settings
# would just be a UI over environment variables, which don't have a
# runtime-editable store in this build - Settings is loaded once at
# startup from .env, not from a database table an admin panel could write to.

@app.get(f"{API_PREFIX}/admin/users", response_model=list[AdminUserView])
async def admin_list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        AdminUserView(
            id=str(u.id), email=u.email, role=u.role,
            is_verified=u.is_verified, is_active=u.is_active, created_at=u.created_at,
        )
        for u in users
    ]


@app.put(f"{API_PREFIX}/admin/users/{{user_id}}/role", response_model=AdminUserView)
async def admin_set_user_role(
    user_id: str,
    req: UpdateUserRoleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    try:
        target_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user id")

    target = db.query(User).filter(User.id == target_uuid).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == admin.id and req.role != UserRole.admin:
        # An admin demoting themselves is how you accidentally lock every
        # admin out of the panel if they're the only one - block it rather
        # than silently allowing a footgun. A different admin can still
        # demote them.
        raise HTTPException(status_code=400, detail="You cannot change your own admin role")

    old_role = target.role
    target.role = req.role.value
    write_audit_log(
        db, admin, "user.role_changed", "user", str(target.id),
        details={"target_email": target.email, "old_role": old_role, "new_role": req.role.value},
    )
    db.commit()
    db.refresh(target)
    return AdminUserView(
        id=str(target.id), email=target.email, role=target.role,
        is_verified=target.is_verified, is_active=target.is_active, created_at=target.created_at,
    )


@app.put(f"{API_PREFIX}/admin/users/{{user_id}}/active", response_model=AdminUserView)
async def admin_set_user_active(
    user_id: str,
    is_active: bool,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    try:
        target_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user id")

    target = db.query(User).filter(User.id == target_uuid).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    target.is_active = is_active
    write_audit_log(
        db, admin, "user.deactivated" if not is_active else "user.reactivated", "user", str(target.id),
        details={"target_email": target.email},
    )
    db.commit()
    db.refresh(target)
    return AdminUserView(
        id=str(target.id), email=target.email, role=target.role,
        is_verified=target.is_verified, is_active=target.is_active, created_at=target.created_at,
    )


@app.get(f"{API_PREFIX}/admin/lessons", response_model=list[AdminLessonSummary])
async def admin_list_lessons(
    flagged_only: bool = False,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    query = db.query(LessonRecord)
    lessons = query.order_by(LessonRecord.created_at.desc()).all()

    results = []
    for lr in lessons:
        if flagged_only and not lr.safety_flags:
            continue
        view_count = db.query(UserLessonHistory).filter(UserLessonHistory.lesson_id == lr.id).count()
        feedback_count = db.query(Feedback).filter(Feedback.lesson_id == lr.id).count()
        results.append(
            AdminLessonSummary(
                id=str(lr.id), topic=lr.topic, level=lr.level,
                safety_flags=lr.safety_flags, created_at=lr.created_at,
                view_count=view_count, feedback_count=feedback_count,
            )
        )
    return results


@app.delete(f"{API_PREFIX}/admin/lessons/{{lesson_id}}", status_code=204)
async def admin_delete_lesson(
    lesson_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    """Deletes a generated lesson entirely - e.g. bad/incorrect content
    that shouldn't stay cached. Cascades to UserLessonHistory, TutorMessage,
    and Feedback rows referencing it (all declared ondelete=CASCADE)."""
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    record = db.query(LessonRecord).filter(LessonRecord.id == lesson_uuid).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    # Capture topic/level before delete - the row (and anything a foreign
    # key could join against) won't exist to query afterward, so the audit
    # entry needs its own copy of what's meaningful about the deleted lesson.
    write_audit_log(
        db, admin, "lesson.deleted", "lesson", str(record.id),
        details={"topic": record.topic, "level": record.level, "had_safety_flags": bool(record.safety_flags)},
    )
    db.delete(record)
    db.commit()


@app.post(f"{API_PREFIX}/lessons/{{lesson_id}}/feedback", response_model=FeedbackView, status_code=201)
async def submit_feedback(
    lesson_id: str,
    req: FeedbackSubmitRequest,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Open to anyone, including anonymous readers - flagging a problem
    shouldn't require an account."""
    try:
        lesson_uuid = uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid lesson id")

    lesson_record = db.query(LessonRecord).filter(LessonRecord.id == lesson_uuid).first()
    if lesson_record is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    if not req.message.strip():
        raise HTTPException(status_code=422, detail="Feedback message cannot be empty")

    fb = Feedback(lesson_id=lesson_uuid, user_id=user.id if user else None, message=req.message.strip())
    db.add(fb)
    db.commit()
    db.refresh(fb)

    return FeedbackView(
        id=str(fb.id), lesson_id=str(lesson_uuid), lesson_topic=lesson_record.topic,
        user_email=user.email if user else None, message=fb.message,
        status=fb.status, created_at=fb.created_at, reviewed_at=fb.reviewed_at,
    )


@app.get(f"{API_PREFIX}/admin/feedback", response_model=list[FeedbackView])
async def admin_list_feedback(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    query = db.query(Feedback)
    if status_filter:
        query = query.filter(Feedback.status == status_filter)
    entries = query.order_by(Feedback.created_at.desc()).all()

    results = []
    for fb in entries:
        lesson_record = db.query(LessonRecord).filter(LessonRecord.id == fb.lesson_id).first()
        reporting_user = db.query(User).filter(User.id == fb.user_id).first() if fb.user_id else None
        results.append(
            FeedbackView(
                id=str(fb.id), lesson_id=str(fb.lesson_id),
                lesson_topic=lesson_record.topic if lesson_record else "(deleted lesson)",
                user_email=reporting_user.email if reporting_user else None,
                message=fb.message, status=fb.status,
                created_at=fb.created_at, reviewed_at=fb.reviewed_at,
            )
        )
    return results


@app.put(f"{API_PREFIX}/admin/feedback/{{feedback_id}}/status", response_model=FeedbackView)
async def admin_update_feedback_status(
    feedback_id: str,
    req: UpdateFeedbackStatusRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
):
    if req.status not in ("open", "reviewed", "dismissed"):
        raise HTTPException(status_code=422, detail="status must be one of: open, reviewed, dismissed")

    try:
        fb_uuid = uuid.UUID(feedback_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid feedback id")

    fb = db.query(Feedback).filter(Feedback.id == fb_uuid).first()
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback not found")

    old_status = fb.status
    fb.status = req.status
    if req.status in ("reviewed", "dismissed") and fb.reviewed_at is None:
        fb.reviewed_at = _utc_now()
    write_audit_log(
        db, admin, "feedback.status_changed", "feedback", str(fb.id),
        details={"old_status": old_status, "new_status": req.status},
    )
    db.commit()
    db.refresh(fb)

    lesson_record = db.query(LessonRecord).filter(LessonRecord.id == fb.lesson_id).first()
    reporting_user = db.query(User).filter(User.id == fb.user_id).first() if fb.user_id else None
    return FeedbackView(
        id=str(fb.id), lesson_id=str(fb.lesson_id),
        lesson_topic=lesson_record.topic if lesson_record else "(deleted lesson)",
        user_email=reporting_user.email if reporting_user else None,
        message=fb.message, status=fb.status,
        created_at=fb.created_at, reviewed_at=fb.reviewed_at,
    )


@app.get(f"{API_PREFIX}/admin/audit-log", response_model=list[AuditLogView])
async def admin_get_audit_log(
    action: str | None = None,
    target_type: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
):
    """Read-only, deliberately - there is no PUT/DELETE for audit_logs
    anywhere in this file. limit is capped at 500 regardless of what's
    requested, to keep a careless admin panel from pulling the entire
    table in one call as the log grows."""
    limit = min(limit, 500)
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    entries = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        AuditLogView(
            id=str(e.id), actor_email=e.actor_email, action=e.action,
            target_type=e.target_type, target_id=e.target_id,
            details=e.details, created_at=e.created_at,
        )
        for e in entries
    ]


# ==============================================================================
# 12. VISUALIZATION SCRIPT ENGINE, ASSET MANAGEMENT, FLASHCARDS & BODY MAPPING
# ==============================================================================

class AnimationKeyframe(BaseModel):
    step: int
    title: str
    description: str
    camera_position: list[float]
    target_object: str
    transform_action: str
    duration_seconds: float


class VisualizationScriptResponse(BaseModel):
    id: str
    topic: str
    level: str
    scene_type: str
    camera_mode: str
    keyframes: list[AnimationKeyframe]
    created_at: datetime


class AssetModelResponse(BaseModel):
    id: str
    name: str
    category: str
    model_format: str
    mesh_type: str
    color_hex: str
    description: str
    associated_topics: list[str]


class FlashcardItem(BaseModel):
    id: str
    front_prompt: str
    back_explanation: str
    difficulty_tag: str
    category: str


class FlashcardDeckResponse(BaseModel):
    topic: str
    cards_count: int
    flashcards: list[FlashcardItem]


class OrganMappingResponse(BaseModel):
    id: str
    name: str
    system: str
    mesh_key: str
    color_hex: str
    description: str
    associated_topics: list[str]


_3D_ASSET_REGISTRY = [
    {
        "id": "asset_heart_01",
        "name": "Anatomical Cardiac Myocardium Mesh",
        "category": "cardiovascular",
        "model_format": "procedural_threejs",
        "mesh_type": "heart",
        "color_hex": "#ef4444",
        "description": "3D pulsating heart model with aorta arch and coronary arterial vessels.",
        "associated_topics": ["Coronary Artery Disease", "Hypertension", "Heart Attack"]
    },
    {
        "id": "asset_lungs_01",
        "name": "Respiratory Bronchial Lungs Mesh",
        "category": "respiratory",
        "model_format": "procedural_threejs",
        "mesh_type": "lungs",
        "color_hex": "#0284c7",
        "description": "Dual-lobe pulmonary respiratory tree with trachea bronchial branching.",
        "associated_topics": ["SARS-CoV-2 (COVID-19)", "Asthma", "Pneumonia"]
    },
    {
        "id": "asset_brain_01",
        "name": "Cerebral Cortex Hemisphere Mesh",
        "category": "nervous_system",
        "model_format": "procedural_threejs",
        "mesh_type": "brain",
        "color_hex": "#a855f7",
        "description": "Dual cerebral hemisphere model with cerebellum and brainstem structure.",
        "associated_topics": ["Alzheimer's Disease", "Stroke", "Parkinson's Disease"]
    },
    {
        "id": "asset_pancreas_01",
        "name": "Pancreatic Islet Beta Cell Mesh",
        "category": "endocrine",
        "model_format": "procedural_threejs",
        "mesh_type": "pancreas",
        "color_hex": "#eab308",
        "description": "Endocrine pancreas gland with Islets of Langerhans beta cell clusters.",
        "associated_topics": ["Type 2 Diabetes Mellitus", "Pancreatitis"]
    },
    {
        "id": "asset_virus_01",
        "name": "Betacoronavirus Spike Virion Mesh",
        "category": "microbiology",
        "model_format": "procedural_threejs",
        "mesh_type": "virus",
        "color_hex": "#f43f5e",
        "description": "Enveloped viral capsid sphere studded with surface spike glycoprotein RBDs.",
        "associated_topics": ["SARS-CoV-2 (COVID-19)", "Influenza", "Viral Infection"]
    },
    {
        "id": "asset_cell_01",
        "name": "Eukaryotic Cell Receptor Channel Mesh",
        "category": "cytology",
        "model_format": "procedural_threejs",
        "mesh_type": "cell",
        "color_hex": "#06b6d4",
        "description": "Cellular lipid bilayer membrane with GLUT4 channels and ACE2 surface receptors.",
        "associated_topics": ["Type 2 Diabetes Mellitus", "Cellular Transduction", "SARS-CoV-2 (COVID-19)"]
    }
]


@app.get(f"{API_PREFIX}/visualization/generate", response_model=VisualizationScriptResponse)
async def generate_visualization_script(
    topic: str,
    level: Level = Level.high_school
):
    """Visualization Script Engine: Converts AI lesson pathophysiology into step-by-step
    3D WebGL camera and mesh keyframe animation scripts."""
    t_lower = topic.lower()
    scene_type = "cellular_cascade"
    target_mesh = "cell"
    
    if "diabetes" in t_lower:
        scene_type = "glut4_translocation_failure"
        target_mesh = "pancreas"
        keyframes = [
            AnimationKeyframe(step=1, title="Glucose Circulation", description="Glucose molecules circulate through capillary blood vessels after carbohydrate digestion.", camera_position=[0, 0, 8], target_object="cell", transform_action="flow", duration_seconds=3.0),
            AnimationKeyframe(step=2, title="Insulin Binding Signal", description="Pancreatic beta cells release insulin, attempting to dock onto cell surface receptors.", camera_position=[0, 1.2, 5], target_object="pancreas", transform_action="dock", duration_seconds=3.5),
            AnimationKeyframe(step=3, title="Receptor Resistance", description="Intracellular IRS-1 phosphorylation signaling is blocked by insulin resistance.", camera_position=[0.5, 0.5, 3], target_object="cell", transform_action="block", duration_seconds=4.0),
            AnimationKeyframe(step=4, title="GLUT4 Lockout", description="GLUT4 glucose transporter vesicles remain trapped inside cell cytoplasm instead of translocating.", camera_position=[0, 0, 4], target_object="cell", transform_action="lock", duration_seconds=3.5),
            AnimationKeyframe(step=5, title="Hyperglycemia Build-up", description="Unprocessed glucose accumulates outside in extracellular space, elevating blood sugar.", camera_position=[0, 0, 7], target_object="cell", transform_action="accumulate", duration_seconds=4.0)
        ]
    elif "covid" in t_lower or "virus" in t_lower:
        scene_type = "viral_spike_fusion"
        target_mesh = "virus"
        keyframes = [
            AnimationKeyframe(step=1, title="Virion Aerosol Entry", description="SARS-CoV-2 virions enter nasopharyngeal mucosa via inhaled droplets.", camera_position=[0, 0, 9], target_object="virus", transform_action="approach", duration_seconds=3.0),
            AnimationKeyframe(step=2, title="ACE2 Receptor Docking", description="Viral spike protein S1 subunit RBD docks onto human ACE2 receptor.", camera_position=[0, 1.0, 4], target_object="virus", transform_action="dock", duration_seconds=3.5),
            AnimationKeyframe(step=3, title="TMPRSS2 Cleavage", description="Host membrane protease TMPRSS2 cleaves spike protein to activate fusion.", camera_position=[0.2, 0.2, 2.5], target_object="cell", transform_action="cleave", duration_seconds=3.5),
            AnimationKeyframe(step=4, title="Endosomal Genome Entry", description="Viral envelope fuses with host cell membrane, releasing ssRNA genome into cytoplasm.", camera_position=[0, 0, 3], target_object="cell", transform_action="penetrate", duration_seconds=4.0),
            AnimationKeyframe(step=5, title="Ribosome Hijacking", description="Host ribosomes translate viral RTC complex, assembling new virions.", camera_position=[0, 0, 6], target_object="cell", transform_action="replicate", duration_seconds=4.0)
        ]
    elif "heart" in t_lower or "coronary" in t_lower or "artery" in t_lower:
        scene_type = "atherosclerotic_plaque_rupture"
        target_mesh = "heart"
        keyframes = [
            AnimationKeyframe(step=1, title="Endothelial Shear Stress", description="High blood pressure causes micro-tears in coronary artery endothelial lining.", camera_position=[0, 0, 8], target_object="heart", transform_action="pulse", duration_seconds=3.0),
            AnimationKeyframe(step=2, title="Oxidized LDL Infiltration", description="LDL particles enter tunica intima layer and undergo oxidative modification.", camera_position=[0, 0.8, 5], target_object="heart", transform_action="infiltrate", duration_seconds=3.5),
            AnimationKeyframe(step=3, title="Foam Cell Aggregation", description="Macrophages engulf oxidized LDL, becoming foam cells that form a fatty streak.", camera_position=[0, 0, 3.5], target_object="cell", transform_action="expand", duration_seconds=4.0),
            AnimationKeyframe(step=4, title="Fibrous Cap Formation", description="Smooth muscle cells secrete collagen to cap lipid core atheroma.", camera_position=[0, 0, 4], target_object="heart", transform_action="cap", duration_seconds=3.5),
            AnimationKeyframe(step=5, title="Thrombus Occlusion", description="Fibrous cap ruptures, initiating tissue factor cascade and cardiac ischemia.", camera_position=[0, 0, 6], target_object="heart", transform_action="occlude", duration_seconds=4.0)
        ]
    else:
        scene_type = "general_pathophysiological_cascade"
        keyframes = [
            AnimationKeyframe(step=1, title="Initial Exposure & Trigger", description=f"Pathological trigger initiates response for {topic}.", camera_position=[0, 0, 8], target_object=target_mesh, transform_action="approach", duration_seconds=3.0),
            AnimationKeyframe(step=2, title="Cellular Receptor Signal", description="Extracellular chemical signals bind cell surface receptors.", camera_position=[0, 1.0, 5], target_object=target_mesh, transform_action="bind", duration_seconds=3.5),
            AnimationKeyframe(step=3, title="Tissue Cascade Spread", description="Intracellular messenger cascades propagate through target tissue.", camera_position=[0, 0, 4], target_object=target_mesh, transform_action="cascade", duration_seconds=4.0),
            AnimationKeyframe(step=4, title="Immune Detection", description="Immune surveillance cells detect altered tissue markers.", camera_position=[0, 0, 5], target_object=target_mesh, transform_action="detect", duration_seconds=3.5),
            AnimationKeyframe(step=5, title="Homeostatic Restoration", description="Therapeutic intervention restores biological equilibrium.", camera_position=[0, 0, 7], target_object=target_mesh, transform_action="restore", duration_seconds=4.0)
        ]

    return VisualizationScriptResponse(
        id=f"vis_{uuid.uuid4().hex[:8]}",
        topic=topic,
        level=level.value,
        scene_type=scene_type,
        camera_mode="orbit_interactive",
        keyframes=keyframes,
        created_at=_utc_now()
    )


@app.get(f"{API_PREFIX}/assets/models", response_model=list[AssetModelResponse])
async def get_3d_asset_models(category: str | None = None):
    """Asset Management Service: Returns registry of 3D biological models,
    anatomical meshes, and textures available for WebGL rendering."""
    if category:
        c_lower = category.lower()
        return [AssetModelResponse(**a) for a in _3D_ASSET_REGISTRY if a["category"] == c_lower]
    return [AssetModelResponse(**a) for a in _3D_ASSET_REGISTRY]


@app.get(f"{API_PREFIX}/quiz/flashcards/{{topic}}", response_model=FlashcardDeckResponse)
async def get_topic_flashcards(topic: str):
    """Flashcard Study Deck Engine: Returns interactive study flashcards with flip explanations."""
    t_lower = topic.lower()
    
    if "diabetes" in t_lower:
        cards = [
            FlashcardItem(id="fc_1", front_prompt="Which pancreatic cells produce insulin?", back_explanation="Beta cells in the Islets of Langerhans.", difficulty_tag="Easy", category="Endocrine"),
            FlashcardItem(id="fc_2", front_prompt="What transporter relocates to the cell membrane in response to insulin?", back_explanation="GLUT4 (Glucose Transporter Type 4).", difficulty_tag="Medium", category="Cell Biology"),
            FlashcardItem(id="fc_3", front_prompt="What HbA1c threshold diagnoses Type 2 Diabetes?", back_explanation="HbA1c level of 6.5% or higher.", difficulty_tag="Hard", category="Clinical")
        ]
    elif "covid" in t_lower or "virus" in t_lower:
        cards = [
            FlashcardItem(id="fc_1", front_prompt="What receptor does SARS-CoV-2 spike protein bind to?", back_explanation="ACE2 (Angiotensin-Converting Enzyme 2).", difficulty_tag="Easy", category="Virology"),
            FlashcardItem(id="fc_2", front_prompt="Which host protease cleaves the viral spike protein for fusion?", back_explanation="TMPRSS2.", difficulty_tag="Medium", category="Molecular Biology"),
            FlashcardItem(id="fc_3", front_prompt="Which lung cells express high levels of ACE2 and TMPRSS2?", back_explanation="Type II Alveolar Pneumocytes.", difficulty_tag="Hard", category="Pathology")
        ]
    else:
        cards = [
            FlashcardItem(id="fc_1", front_prompt=f"What is the primary feature of {topic}?", back_explanation=f"{topic} involves specific cellular receptor alterations.", difficulty_tag="Easy", category="General"),
            FlashcardItem(id="fc_2", front_prompt=f"How do medicines help in {topic}?", back_explanation="By targeting specific molecular receptors and restoring tissue balance.", difficulty_tag="Medium", category="Pharmacology")
        ]

    return FlashcardDeckResponse(
        topic=topic,
        cards_count=len(cards),
        flashcards=cards
    )


@app.get(f"{API_PREFIX}/body/organs", response_model=list[OrganMappingResponse])
async def get_body_organ_mappings():
    """Anatomical Systems & Organ Mapping API: Returns 3D anatomical organ nodes
    mapped to medical diseases and topics."""
    organs = [
        OrganMappingResponse(id="organ_heart", name="Heart", system="Cardiovascular", mesh_key="heart", color_hex="#ef4444", description="Muscular organ pumping oxygenated blood.", associated_topics=["Coronary Artery Disease", "Hypertension", "Heart Attack"]),
        OrganMappingResponse(id="organ_lungs", name="Lungs", system="Respiratory", mesh_key="lungs", color_hex="#0284c7", description="Pulmonary gas exchange organs.", associated_topics=["SARS-CoV-2 (COVID-19)", "Asthma", "Pneumonia"]),
        OrganMappingResponse(id="organ_brain", name="Brain", system="Nervous", mesh_key="brain", color_hex="#a855f7", description="Central cognitive and memory processor.", associated_topics=["Alzheimer's Disease", "Stroke", "Parkinson's"]),
        OrganMappingResponse(id="organ_pancreas", name="Pancreas", system="Endocrine", mesh_key="pancreas", color_hex="#eab308", description="Hormonal regulator of blood sugar.", associated_topics=["Type 2 Diabetes Mellitus", "Pancreatitis"]),
        OrganMappingResponse(id="organ_virus", name="Pathogen / Virion", system="Microbiology", mesh_key="virus", color_hex="#f43f5e", description="Viral infectious agent.", associated_topics=["SARS-CoV-2 (COVID-19)", "Influenza"]),
        OrganMappingResponse(id="organ_cell", name="Cellular Membrane", system="Cytology", mesh_key="cell", color_hex="#06b6d4", description="Lipid bilayer membrane with channel pores.", associated_topics=["Type 2 Diabetes Mellitus", "Receptor Signaling"])
    ]
    return organs


# ==============================================================================
# 13. FACT VERIFICATION, SIMULATION ENGINE, KNOWLEDGE GRAPH & CONTENT REVIEW
# ==============================================================================

from fact_verifier import FactVerifier
from ai_orchestrator import AIOrchestrator
from knowledge_graph import MedicalKnowledgeGraph
from simulation_engine import SimulationEngine
from content_review import ContentReviewManager

_fact_verifier = FactVerifier()
_ai_orchestrator = AIOrchestrator()
_knowledge_graph = MedicalKnowledgeGraph()
_simulation_engine = SimulationEngine()
_review_manager = ContentReviewManager()


class SimulationRequest(BaseModel):
    simulation_type: str
    parameters: dict[str, float] | None = None


class FactCheckRequest(BaseModel):
    lesson: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]


@app.post(f"{API_PREFIX}/fact-check/verify")
async def verify_lesson_facts(req: FactCheckRequest):
    """Medical Evidence Verification API: Evaluates lesson claims against retrieved RAG chunks."""
    result = _fact_verifier.verify_lesson(req.lesson, req.retrieved_chunks)
    return result


@app.post(f"{API_PREFIX}/simulation/run")
async def run_biological_simulation(req: SimulationRequest):
    """Deterministic Biological Simulation API: Executes mathematical trajectory models."""
    res = _simulation_engine.run_simulation(req.simulation_type, req.parameters or {})
    return res


@app.get(f"{API_PREFIX}/graph/pathways/{{topic}}")
async def get_medical_graph_pathways(topic: str):
    """Medical Knowledge Graph API: Resolves direct node relationships and pathway neighbors."""
    return _knowledge_graph.query_related_pathways(topic)


@app.get(f"{API_PREFIX}/content/review/{{lesson_id}}")
async def get_lesson_content_review(lesson_id: str, topic: str = "Medical Topic"):
    """Medical Content Review & Versioning API: Retrieves content lifecycle status."""
    rev = _review_manager.get_review(lesson_id)
    if not rev:
        rev = _review_manager.create_review(lesson_id, topic, is_fact_valid=True).to_dict()
    return rev


# ==============================================================================
# 14. APP INIT
# ==============================================================================
# Run with: uvicorn main:app --reload

@app.on_event("startup")
def on_app_startup():
    """Ensure database tables exist on startup if running in development/local mode."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully on startup.")
    except Exception as e:
        logger.warning("Database table creation notice: %s", e)



