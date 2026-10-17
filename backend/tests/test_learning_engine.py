"""
Tests for the Learning Engine routes: record_lesson_view, set_bookmark,
submit_quiz (including best-score-across-attempts retention), get_history,
get_learning_stats.
"""
import asyncio

import pytest

from conftest import make_lessons_table, make_user_lesson_history_table, make_users_table


@pytest.fixture
def learning_setup(db_session, app):
    """Common setup shared by every test in this file: users + lessons +
    user_lesson_history tables swapped in, one user, one lesson with a
    2-question quiz."""
    session, engine = db_session
    users_table = make_users_table()
    lessons_table = make_lessons_table()
    history_table = make_user_lesson_history_table()
    users_table.metadata.create_all(engine)
    lessons_table.metadata.create_all(engine)
    history_table.metadata.create_all(engine)
    app.User.__table__ = users_table
    app.LessonRecord.__table__ = lessons_table
    app.UserLessonHistory.__table__ = history_table

    user = app.User(email="learner@example.com", hashed_password="h", role="student")
    session.add(user)
    session.commit()

    lesson = app.Lesson(
        topic="diabetes", level="general_public",
        sections=[{"id": "what_is_it", "title": "What is it?", "content": "Diabetes affects blood sugar.", "sources": []}],
        quiz=[
            {"question": "What does diabetes affect?", "options": ["Blood sugar", "Hair", "Vision only", "Height"], "correct_index": 0, "explanation": "Blood sugar regulation."},
            {"question": "Is diabetes contagious?", "options": ["Yes", "No"], "correct_index": 1, "explanation": "Not contagious."},
        ],
    )
    lesson_record = app.LessonRecord(topic="diabetes", level="general_public", content=lesson.model_dump(mode="json"), model_versions={}, safety_flags=[])
    session.add(lesson_record)
    session.commit()
    session.refresh(lesson_record)

    return session, app, user, lesson_record


def test_record_view_creates_history_entry(learning_setup):
    session, app, user, lesson_record = learning_setup
    asyncio.run(app.record_lesson_view(str(lesson_record.id), user=user, db=session))

    entry = session.query(app.UserLessonHistory).filter(
        app.UserLessonHistory.user_id == user.id, app.UserLessonHistory.lesson_id == lesson_record.id
    ).first()
    assert entry is not None


def test_record_view_nonexistent_lesson_404s(learning_setup):
    import uuid
    session, app, user, _ = learning_setup
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.record_lesson_view(str(uuid.uuid4()), user=user, db=session))
    assert exc_info.value.status_code == 404


def test_set_bookmark_toggles_correctly(learning_setup):
    session, app, user, lesson_record = learning_setup
    asyncio.run(app.set_bookmark(str(lesson_record.id), bookmarked=True, user=user, db=session))
    entry = session.query(app.UserLessonHistory).filter(
        app.UserLessonHistory.user_id == user.id, app.UserLessonHistory.lesson_id == lesson_record.id
    ).first()
    assert entry.bookmarked is True

    asyncio.run(app.set_bookmark(str(lesson_record.id), bookmarked=False, user=user, db=session))
    session.refresh(entry)
    assert entry.bookmarked is False


def test_submit_quiz_scores_correctly(learning_setup):
    session, app, user, lesson_record = learning_setup
    req = app.QuizSubmitRequest(answers=[0, 0])  # Q1 correct, Q2 wrong (should be 1)
    result = asyncio.run(app.submit_quiz(str(lesson_record.id), req, user=user, db=session))
    assert result.score == 0.5
    assert result.correct_count == 1
    assert result.total == 2


def test_submit_quiz_wrong_answer_count_rejected(learning_setup):
    session, app, user, lesson_record = learning_setup
    req = app.QuizSubmitRequest(answers=[0])  # only 1 answer for a 2-question quiz
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.submit_quiz(str(lesson_record.id), req, user=user, db=session))
    assert exc_info.value.status_code == 422


def test_submit_quiz_retains_best_score_across_attempts(learning_setup):
    """A retake should never make the recorded score worse - it reflects
    mastery, not just the most recent attempt."""
    session, app, user, lesson_record = learning_setup

    worse_req = app.QuizSubmitRequest(answers=[0, 0])  # 1/2 = 0.5
    asyncio.run(app.submit_quiz(str(lesson_record.id), worse_req, user=user, db=session))

    better_req = app.QuizSubmitRequest(answers=[0, 1])  # 2/2 = 1.0
    asyncio.run(app.submit_quiz(str(lesson_record.id), better_req, user=user, db=session))

    entry = session.query(app.UserLessonHistory).filter(
        app.UserLessonHistory.user_id == user.id, app.UserLessonHistory.lesson_id == lesson_record.id
    ).first()
    assert float(entry.quiz_score) == 1.0
    assert entry.quiz_attempts == 2

    # Now submit a worse score again - the stored score must NOT drop back down
    asyncio.run(app.submit_quiz(str(lesson_record.id), worse_req, user=user, db=session))
    session.refresh(entry)
    assert float(entry.quiz_score) == 1.0
    assert entry.quiz_attempts == 3


def test_submit_quiz_marks_completed(learning_setup):
    session, app, user, lesson_record = learning_setup
    req = app.QuizSubmitRequest(answers=[0, 1])
    asyncio.run(app.submit_quiz(str(lesson_record.id), req, user=user, db=session))
    entry = session.query(app.UserLessonHistory).filter(
        app.UserLessonHistory.user_id == user.id, app.UserLessonHistory.lesson_id == lesson_record.id
    ).first()
    assert entry.completed is True


def test_get_history_returns_correct_entry(learning_setup):
    session, app, user, lesson_record = learning_setup
    asyncio.run(app.record_lesson_view(str(lesson_record.id), user=user, db=session))
    asyncio.run(app.set_bookmark(str(lesson_record.id), bookmarked=True, user=user, db=session))

    history = asyncio.run(app.get_history(completed_only=False, bookmarked_only=False, user=user, db=session))
    assert len(history) == 1
    assert history[0].topic == "diabetes"
    assert history[0].bookmarked is True


def test_get_history_bookmarked_only_filter(learning_setup):
    session, app, user, lesson_record = learning_setup
    asyncio.run(app.record_lesson_view(str(lesson_record.id), user=user, db=session))
    # not bookmarked
    history = asyncio.run(app.get_history(completed_only=False, bookmarked_only=True, user=user, db=session))
    assert history == []


def test_get_learning_stats_computes_correctly(learning_setup):
    session, app, user, lesson_record = learning_setup
    asyncio.run(app.record_lesson_view(str(lesson_record.id), user=user, db=session))
    req = app.QuizSubmitRequest(answers=[0, 1])  # perfect score
    asyncio.run(app.submit_quiz(str(lesson_record.id), req, user=user, db=session))
    asyncio.run(app.set_bookmark(str(lesson_record.id), bookmarked=True, user=user, db=session))

    stats = asyncio.run(app.get_learning_stats(user=user, db=session))
    assert stats.lessons_viewed == 1
    assert stats.lessons_completed == 1
    assert stats.lessons_bookmarked == 1
    assert stats.average_quiz_score == 1.0
    assert stats.topics_covered == ["diabetes"]
