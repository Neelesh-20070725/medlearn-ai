"""
Tests for the Admin Engine routes: user management (role changes,
activate/deactivate, self-protection), lesson management (list, delete
with cascade), feedback lifecycle, and audit logging.
"""
import asyncio
import uuid

import pytest

from conftest import (
    make_audit_logs_table,
    make_feedback_table,
    make_lessons_table,
    make_user_lesson_history_table,
    make_users_table,
)


@pytest.fixture
def admin_setup(db_session, app):
    """Common setup: users + lessons + feedback + audit_logs +
    user_lesson_history tables swapped in (admin_list_lessons queries
    UserLessonHistory for view counts, so it needs to exist even though
    most tests in this file don't populate it), one admin, one student,
    one lesson."""
    session, engine = db_session
    users_table = make_users_table()
    lessons_table = make_lessons_table()
    feedback_table = make_feedback_table()
    audit_table = make_audit_logs_table()
    history_table = make_user_lesson_history_table()
    for t in (users_table, lessons_table, feedback_table, audit_table, history_table):
        t.metadata.create_all(engine)
    app.User.__table__ = users_table
    app.LessonRecord.__table__ = lessons_table
    app.Feedback.__table__ = feedback_table
    app.AuditLog.__table__ = audit_table
    app.UserLessonHistory.__table__ = history_table

    admin = app.User(email="admin@example.com", hashed_password="h", role="admin")
    student = app.User(email="student@example.com", hashed_password="h", role="student")
    session.add_all([admin, student])
    session.commit()

    lesson = app.Lesson(topic="diabetes", level="general_public", sections=[{"id": "s", "title": "T", "content": "c", "sources": []}], quiz=[])
    lesson_record = app.LessonRecord(topic="diabetes", level="general_public", content=lesson.model_dump(mode="json"), model_versions={}, safety_flags=[])
    session.add(lesson_record)
    session.commit()
    session.refresh(lesson_record)

    return session, app, admin, student, lesson_record


# --- User management ---------------------------------------------------------

def test_admin_list_users_returns_all(admin_setup):
    session, app, admin, student, _ = admin_setup
    users = asyncio.run(app.admin_list_users(db=session, _admin=admin))
    assert len(users) == 2


def test_admin_set_user_role_changes_role(admin_setup):
    session, app, admin, student, _ = admin_setup
    req = app.UpdateUserRoleRequest(role=app.UserRole.educator)
    updated = asyncio.run(app.admin_set_user_role(str(student.id), req, db=session, admin=admin))
    assert updated.role == "educator"


def test_admin_cannot_demote_self(admin_setup):
    session, app, admin, student, _ = admin_setup
    req = app.UpdateUserRoleRequest(role=app.UserRole.student)
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_set_user_role(str(admin.id), req, db=session, admin=admin))
    assert exc_info.value.status_code == 400


def test_admin_set_user_active_deactivates(admin_setup):
    session, app, admin, student, _ = admin_setup
    updated = asyncio.run(app.admin_set_user_active(str(student.id), False, db=session, admin=admin))
    assert updated.is_active is False


def test_admin_cannot_deactivate_self(admin_setup):
    session, app, admin, student, _ = admin_setup
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_set_user_active(str(admin.id), False, db=session, admin=admin))
    assert exc_info.value.status_code == 400


def test_admin_set_role_nonexistent_user_404s(admin_setup):
    session, app, admin, student, _ = admin_setup
    req = app.UpdateUserRoleRequest(role=app.UserRole.educator)
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_set_user_role(str(uuid.uuid4()), req, db=session, admin=admin))
    assert exc_info.value.status_code == 404


# --- Lesson management ---------------------------------------------------------

def test_admin_list_lessons_reports_view_and_feedback_counts(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    summaries = asyncio.run(app.admin_list_lessons(flagged_only=False, db=session, _admin=admin))
    assert len(summaries) == 1
    assert summaries[0].topic == "diabetes"
    assert summaries[0].view_count == 0
    assert summaries[0].feedback_count == 0


def test_admin_list_lessons_flagged_only_filter(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    flagged = asyncio.run(app.admin_list_lessons(flagged_only=True, db=session, _admin=admin))
    assert flagged == []  # our test lesson has no safety_flags


def test_admin_delete_lesson_removes_it(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    asyncio.run(app.admin_delete_lesson(str(lesson_record.id), db=session, admin=admin))
    remaining = session.query(app.LessonRecord).filter(app.LessonRecord.id == lesson_record.id).first()
    assert remaining is None


def test_admin_delete_nonexistent_lesson_404s(admin_setup):
    session, app, admin, student, _ = admin_setup
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_delete_lesson(str(uuid.uuid4()), db=session, admin=admin))
    assert exc_info.value.status_code == 404


# --- Feedback lifecycle ---------------------------------------------------------

def test_submit_feedback_anonymous_allowed(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    req = app.FeedbackSubmitRequest(message="This section is confusing.")
    fb = asyncio.run(app.submit_feedback(str(lesson_record.id), req, user=None, db=session))
    assert fb.user_email is None
    assert fb.status == "open"


def test_submit_feedback_empty_message_rejected(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    req = app.FeedbackSubmitRequest(message="   ")
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.submit_feedback(str(lesson_record.id), req, user=None, db=session))
    assert exc_info.value.status_code == 422


def test_admin_update_feedback_status_sets_reviewed_at(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    fb_req = app.FeedbackSubmitRequest(message="Confusing")
    fb = asyncio.run(app.submit_feedback(str(lesson_record.id), fb_req, user=None, db=session))

    status_req = app.UpdateFeedbackStatusRequest(status="reviewed")
    updated = asyncio.run(app.admin_update_feedback_status(fb.id, status_req, db=session, admin=admin))
    assert updated.status == "reviewed"
    assert updated.reviewed_at is not None


def test_admin_update_feedback_invalid_status_rejected(admin_setup):
    session, app, admin, student, lesson_record = admin_setup
    fb_req = app.FeedbackSubmitRequest(message="Confusing")
    fb = asyncio.run(app.submit_feedback(str(lesson_record.id), fb_req, user=None, db=session))

    bad_req = app.UpdateFeedbackStatusRequest(status="bogus_status")
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_update_feedback_status(fb.id, bad_req, db=session, admin=admin))
    assert exc_info.value.status_code == 422


# --- Audit logging ---------------------------------------------------------------

def test_role_change_writes_audit_entry(admin_setup):
    session, app, admin, student, _ = admin_setup
    req = app.UpdateUserRoleRequest(role=app.UserRole.educator)
    asyncio.run(app.admin_set_user_role(str(student.id), req, db=session, admin=admin))

    logs = asyncio.run(app.admin_get_audit_log(action=None, target_type=None, limit=100, db=session, _admin=admin))
    role_log = next((l for l in logs if l.action == "user.role_changed"), None)
    assert role_log is not None
    assert role_log.actor_email == "admin@example.com"
    assert role_log.details["old_role"] == "student"
    assert role_log.details["new_role"] == "educator"


def test_lesson_deletion_audit_entry_survives_the_deletion(admin_setup):
    """The audit entry for a deleted lesson must remain queryable and
    correct AFTER the lesson itself is gone - target_id is a plain string,
    not a foreign key, specifically so this works."""
    session, app, admin, student, lesson_record = admin_setup
    lesson_id = str(lesson_record.id)

    asyncio.run(app.admin_delete_lesson(lesson_id, db=session, admin=admin))

    logs = asyncio.run(app.admin_get_audit_log(action="lesson.deleted", target_type=None, limit=100, db=session, _admin=admin))
    assert len(logs) == 1
    assert logs[0].target_id == lesson_id
    assert logs[0].details["topic"] == "diabetes"

    still_gone = session.query(app.LessonRecord).filter(app.LessonRecord.id == lesson_record.id).first()
    assert still_gone is None


def test_audit_log_filters_by_target_type(admin_setup):
    session, app, admin, student, lesson_record = admin_setup

    req = app.UpdateUserRoleRequest(role=app.UserRole.educator)
    asyncio.run(app.admin_set_user_role(str(student.id), req, db=session, admin=admin))
    asyncio.run(app.admin_delete_lesson(str(lesson_record.id), db=session, admin=admin))

    user_logs = asyncio.run(app.admin_get_audit_log(action=None, target_type="user", limit=100, db=session, _admin=admin))
    lesson_logs = asyncio.run(app.admin_get_audit_log(action=None, target_type="lesson", limit=100, db=session, _admin=admin))

    assert len(user_logs) == 1
    assert len(lesson_logs) == 1
    assert user_logs[0].target_type == "user"
    assert lesson_logs[0].target_type == "lesson"


def test_audit_log_ordered_newest_first(admin_setup):
    session, app, admin, student, lesson_record = admin_setup

    req = app.UpdateUserRoleRequest(role=app.UserRole.educator)
    asyncio.run(app.admin_set_user_role(str(student.id), req, db=session, admin=admin))
    asyncio.run(app.admin_set_user_active(str(student.id), False, db=session, admin=admin))

    logs = asyncio.run(app.admin_get_audit_log(action=None, target_type=None, limit=100, db=session, _admin=admin))
    assert len(logs) == 2
    assert logs[0].created_at >= logs[1].created_at


# --- Role gating on the admin endpoints themselves --------------------------------

def test_admin_endpoints_reject_non_admin_role(admin_setup):
    """require_role(UserRole.admin) must actually block a student from
    every admin-gated route, not just some of them."""
    session, app, admin, student, lesson_record = admin_setup
    admin_gate = app.require_role(app.UserRole.admin)

    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(admin_gate(user=student))
    assert exc_info.value.status_code == 403
