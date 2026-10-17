"""
Medical Content Review & Versioning Engine for MedLearn AI.
Manages lesson lifecycle states (draft, validation_failed, review_required,
approved, published, archived), tracks content/source schema versions, and
triggers revalidation when RAG sources update.

Storage: persists review records to the `content_reviews` table in the
application database. Falls back gracefully to in-memory storage when a
DB session is not provided (useful for unit tests).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("medlearn.content_review")

VALID_STATUSES = frozenset(
    {"draft", "validation_failed", "review_required", "approved", "published", "archived"}
)


class LessonReviewRecord:
    """In-memory representation of one content-review record."""

    def __init__(
        self,
        lesson_id: str,
        topic: str,
        content_version: str = "1.0.0",
        source_version: str = "2026.1",
        status: str = "draft",
    ):
        self.record_id = f"rev_{uuid.uuid4().hex[:8]}"
        self.lesson_id = lesson_id
        self.topic = topic
        self.content_version = content_version
        self.source_version = source_version
        self.status = status
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.reviewed_by: Optional[str] = None
        self.review_notes: Optional[str] = None

    def transition_status(
        self, new_status: str, reviewer: str | None = None, notes: str | None = None
    ) -> bool:
        if new_status not in VALID_STATUSES:
            return False
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if reviewer:
            self.reviewed_by = reviewer
        if notes:
            self.review_notes = notes
        return True

    def mark_for_revalidation(self, new_source_version: str) -> None:
        self.source_version = new_source_version
        self.status = "review_required"
        self.review_notes = (
            f"Source updated to {new_source_version}. Automatic revalidation triggered."
        )
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "lesson_id": self.lesson_id,
            "topic": self.topic,
            "content_version": self.content_version,
            "source_version": self.source_version,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "reviewed_by": self.reviewed_by,
            "review_notes": self.review_notes,
        }


def _try_db_get(db, lesson_id: str) -> Optional[Dict[str, Any]]:
    """Attempt to fetch a review row from the DB. Returns None on any failure."""
    if db is None:
        return None
    try:
        from sqlalchemy import text as _sql_text

        row = db.execute(
            _sql_text(
                "SELECT record_id, lesson_id, topic, content_version, source_version, "
                "status, created_at, updated_at, reviewed_by, review_notes "
                "FROM content_reviews WHERE lesson_id = :lid LIMIT 1"
            ),
            {"lid": lesson_id},
        ).fetchone()
        if row is None:
            return None
        return {
            "record_id": row.record_id,
            "lesson_id": row.lesson_id,
            "topic": row.topic,
            "content_version": row.content_version,
            "source_version": row.source_version,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "reviewed_by": row.reviewed_by,
            "review_notes": row.review_notes,
        }
    except Exception as exc:
        logger.debug("content_reviews DB read failed (table may not exist yet): %s", exc)
        return None


def _try_db_upsert(db, rec: LessonReviewRecord) -> bool:
    """Upsert a review record into the DB. Returns True on success."""
    if db is None:
        return False
    try:
        from sqlalchemy import text as _sql_text

        db.execute(
            _sql_text(
                """
                INSERT INTO content_reviews
                    (record_id, lesson_id, topic, content_version, source_version,
                     status, created_at, updated_at, reviewed_by, review_notes)
                VALUES
                    (:record_id, :lesson_id, :topic, :content_version, :source_version,
                     :status, :created_at, :updated_at, :reviewed_by, :review_notes)
                ON CONFLICT (lesson_id) DO UPDATE SET
                    status         = EXCLUDED.status,
                    source_version = EXCLUDED.source_version,
                    content_version = EXCLUDED.content_version,
                    updated_at     = EXCLUDED.updated_at,
                    reviewed_by    = EXCLUDED.reviewed_by,
                    review_notes   = EXCLUDED.review_notes
                """
            ),
            {
                "record_id": rec.record_id,
                "lesson_id": rec.lesson_id,
                "topic": rec.topic,
                "content_version": rec.content_version,
                "source_version": rec.source_version,
                "status": rec.status,
                "created_at": rec.created_at,
                "updated_at": rec.updated_at,
                "reviewed_by": rec.reviewed_by,
                "review_notes": rec.review_notes,
            },
        )
        db.commit()
        return True
    except Exception as exc:
        logger.debug("content_reviews DB write failed (table may not exist yet): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


class ContentReviewManager:
    """
    Manages lesson review lifecycle with DB persistence.

    All public methods accept an optional `db` keyword argument (a
    SQLAlchemy Session). When provided, the manager reads/writes from the
    `content_reviews` table. When omitted (or when the table doesn't exist
    yet), it falls back to an in-memory dict — correct for unit tests and
    early local development before the migration is applied.
    """

    def __init__(self) -> None:
        # In-memory fallback store — used when DB is unavailable or table
        # not yet created. Keys are lesson_id strings.
        self._reviews: Dict[str, LessonReviewRecord] = {}

    def create_review(
        self,
        lesson_id: str,
        topic: str,
        is_fact_valid: bool = True,
        db=None,
    ) -> LessonReviewRecord:
        status = "published" if is_fact_valid else "review_required"
        rec = LessonReviewRecord(lesson_id=lesson_id, topic=topic, status=status)
        self._reviews[lesson_id] = rec
        _try_db_upsert(db, rec)
        return rec

    def get_review(self, lesson_id: str, db=None) -> Optional[Dict[str, Any]]:
        # Try DB first for freshest data.
        db_row = _try_db_get(db, lesson_id)
        if db_row is not None:
            return db_row
        # Fall back to in-memory.
        if lesson_id in self._reviews:
            return self._reviews[lesson_id].to_dict()
        return None

    def update_review_status(
        self,
        lesson_id: str,
        new_status: str,
        reviewer: str = "medical_admin",
        notes: Optional[str] = None,
        db=None,
    ) -> Optional[Dict[str, Any]]:
        # Try to load from DB first so updates survive restarts.
        db_row = _try_db_get(db, lesson_id)
        if db_row is not None and lesson_id not in self._reviews:
            # Reconstruct an in-memory record from DB data so we can mutate it.
            rec = LessonReviewRecord(
                lesson_id=db_row["lesson_id"],
                topic=db_row["topic"],
                content_version=db_row["content_version"],
                source_version=db_row["source_version"],
                status=db_row["status"],
            )
            rec.record_id = db_row["record_id"]
            rec.reviewed_by = db_row["reviewed_by"]
            rec.review_notes = db_row["review_notes"]
            self._reviews[lesson_id] = rec

        if lesson_id not in self._reviews:
            return None

        rec = self._reviews[lesson_id]
        if not rec.transition_status(new_status, reviewer, notes):
            return None

        _try_db_upsert(db, rec)
        return rec.to_dict()

    def trigger_revalidation(
        self,
        new_source_version: str,
        db=None,
    ) -> List[Dict[str, Any]]:
        """Mark every review record as review_required when sources update."""
        affected = []
        for rec in self._reviews.values():
            rec.mark_for_revalidation(new_source_version)
            _try_db_upsert(db, rec)
            affected.append(rec.to_dict())
        return affected
