"""
Tests for the ContentReviewManager in content_review.py.

Tests cover:
  - create_review sets correct initial status (published for valid, review_required for invalid)
  - get_review returns the record after creation
  - update_review_status transitions to a valid status
  - update_review_status rejects an invalid status
  - update_review_status returns None for a non-existent lesson
  - trigger_revalidation marks all records as review_required
  - In-memory fallback works with no DB session provided
"""
import pytest

import sys
import os
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/medlearn_test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ["TESTING"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from content_review import ContentReviewManager, LessonReviewRecord, VALID_STATUSES


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_manager():
    """Fresh manager with empty in-memory store for each test."""
    return ContentReviewManager()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_create_review_valid_fact_sets_published():
    mgr = make_manager()
    rec = mgr.create_review("lesson-001", "Diabetes", is_fact_valid=True)
    assert rec.status == "published"
    assert rec.lesson_id == "lesson-001"
    assert rec.topic == "Diabetes"


def test_create_review_invalid_fact_sets_review_required():
    mgr = make_manager()
    rec = mgr.create_review("lesson-002", "Hypertension", is_fact_valid=False)
    assert rec.status == "review_required"


def test_get_review_returns_record_after_creation():
    mgr = make_manager()
    mgr.create_review("lesson-003", "Asthma")
    result = mgr.get_review("lesson-003")
    assert result is not None
    assert result["lesson_id"] == "lesson-003"
    assert result["topic"] == "Asthma"


def test_get_review_returns_none_for_unknown_lesson():
    mgr = make_manager()
    result = mgr.get_review("nonexistent-lesson-id")
    assert result is None


def test_update_review_status_transitions_correctly():
    mgr = make_manager()
    mgr.create_review("lesson-004", "Stroke")
    updated = mgr.update_review_status("lesson-004", "approved", reviewer="admin@example.com")
    assert updated is not None
    assert updated["status"] == "approved"
    assert updated["reviewed_by"] == "admin@example.com"


def test_update_review_status_rejects_invalid_status():
    mgr = make_manager()
    mgr.create_review("lesson-005", "Migraine")
    result = mgr.update_review_status("lesson-005", "invalid_state")
    assert result is None


def test_update_review_status_returns_none_for_unknown_lesson():
    mgr = make_manager()
    result = mgr.update_review_status("ghost-lesson", "approved")
    assert result is None


def test_update_review_status_sets_notes():
    mgr = make_manager()
    mgr.create_review("lesson-006", "COVID-19")
    updated = mgr.update_review_status(
        "lesson-006",
        "validation_failed",
        notes="Hallucination detected in cellular mechanism section.",
    )
    assert updated["review_notes"] == "Hallucination detected in cellular mechanism section."


def test_trigger_revalidation_marks_all_records():
    mgr = make_manager()
    mgr.create_review("lesson-007", "Diabetes", is_fact_valid=True)
    mgr.create_review("lesson-008", "Asthma", is_fact_valid=True)
    mgr.create_review("lesson-009", "Stroke", is_fact_valid=True)

    affected = mgr.trigger_revalidation("2026.2")
    assert len(affected) == 3
    for record in affected:
        assert record["status"] == "review_required"
        assert record["source_version"] == "2026.2"


def test_all_valid_status_transitions_work():
    for status in VALID_STATUSES:
        mgr = make_manager()
        mgr.create_review("lesson-x", "Generic Topic")
        result = mgr.update_review_status("lesson-x", status)
        assert result is not None, f"Transition to '{status}' should succeed"
        assert result["status"] == status


def test_lesson_review_record_to_dict_has_all_fields():
    rec = LessonReviewRecord("lesson-010", "Parkinson's", status="draft")
    d = rec.to_dict()
    required_keys = {
        "record_id", "lesson_id", "topic", "content_version",
        "source_version", "status", "created_at", "updated_at",
        "reviewed_by", "review_notes",
    }
    assert required_keys.issubset(set(d.keys()))


def test_multiple_updates_reflect_latest_state():
    mgr = make_manager()
    mgr.create_review("lesson-011", "Epilepsy")
    mgr.update_review_status("lesson-011", "approved")
    mgr.update_review_status("lesson-011", "archived")
    final = mgr.get_review("lesson-011")
    assert final["status"] == "archived"
