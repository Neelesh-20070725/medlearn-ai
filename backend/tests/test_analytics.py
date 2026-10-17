"""
Tests for the Analytics Engine (main.py's _compute_user_analytics,
_compute_search_analytics, _compute_quiz_analytics,
_compute_tutor_analytics, and the get_platform_analytics endpoint).

Every number these functions compute is checked against a manually
worked-out expected value from a hand-seeded dataset, not just "did it
run without erroring" - this mirrors the original manual verification
approach used during development, now committed as permanent tests.
"""
import asyncio

import pytest

from conftest import (
    make_lessons_table,
    make_tutor_messages_table,
    make_user_lesson_history_table,
    make_users_table,
)


@pytest.fixture
def analytics_setup(db_session, app):
    """A hand-seeded dataset: 3 users (2 students - one verified, one
    not - and 1 admin), 3 lessons (diabetes generated at 2 levels,
    asthma at 1 level), mixed view/quiz history, and mixed
    anonymous/signed-in tutor activity. Every test in this file checks
    a specific number against what this dataset should produce by hand."""
    session, engine = db_session
    users_table = make_users_table()
    lessons_table = make_lessons_table()
    history_table = make_user_lesson_history_table()
    tutor_table = make_tutor_messages_table()
    for t in (users_table, lessons_table, history_table, tutor_table):
        t.metadata.create_all(engine)
    app.User.__table__ = users_table
    app.LessonRecord.__table__ = lessons_table
    app.UserLessonHistory.__table__ = history_table
    app.TutorMessage.__table__ = tutor_table

    u1 = app.User(email="a@x.com", hashed_password="h", role="student", is_verified=True)
    u2 = app.User(email="b@x.com", hashed_password="h", role="student", is_verified=False)
    u3 = app.User(email="admin@x.com", hashed_password="h", role="admin", is_verified=True)
    session.add_all([u1, u2, u3])
    session.commit()

    def make_lesson(topic, level):
        l = app.Lesson(topic=topic, level=level, sections=[{"id": "s", "title": "T", "content": "c", "sources": []}], quiz=[])
        r = app.LessonRecord(topic=topic, level=level, content=l.model_dump(mode="json"), model_versions={}, safety_flags=[])
        session.add(r)
        session.commit()
        session.refresh(r)
        return r

    diabetes_general = make_lesson("diabetes", "general_public")
    diabetes_child = make_lesson("diabetes", "child")
    asthma_lesson = make_lesson("asthma", "general_public")

    # u1 views diabetes_general: completed, score 0.8, 2 attempts, bookmarked
    h1 = app.UserLessonHistory(user_id=u1.id, lesson_id=diabetes_general.id, quiz_score=0.8, quiz_attempts=2, completed=True, bookmarked=True)
    # u2 views diabetes_general: not completed, no quiz attempt
    h2 = app.UserLessonHistory(user_id=u2.id, lesson_id=diabetes_general.id, quiz_attempts=0, completed=False)
    # u2 views asthma: completed, score 1.0, 1 attempt
    h3 = app.UserLessonHistory(user_id=u2.id, lesson_id=asthma_lesson.id, quiz_score=1.0, quiz_attempts=1, completed=True)
    session.add_all([h1, h2, h3])
    session.commit()

    # Tutor: u1 asks 1 question (2 messages) on diabetes_general; anonymous asks 1 (2 messages) on asthma
    session.add_all([
        app.TutorMessage(lesson_id=diabetes_general.id, user_id=u1.id, role="user", content="Why?"),
        app.TutorMessage(lesson_id=diabetes_general.id, user_id=u1.id, role="assistant", content="Because..."),
        app.TutorMessage(lesson_id=asthma_lesson.id, user_id=None, role="user", content="What causes it?"),
        app.TutorMessage(lesson_id=asthma_lesson.id, user_id=None, role="assistant", content="Triggers..."),
    ])
    session.commit()

    return session, app, u1, u2, u3, diabetes_general, diabetes_child, asthma_lesson


def test_user_analytics_counts_and_roles(analytics_setup):
    session, app = analytics_setup[0], analytics_setup[1]
    stats = app._compute_user_analytics(session)
    assert stats.total_users == 3
    assert stats.verified_users == 2
    assert stats.users_by_role == {"student": 2, "admin": 1}


def test_search_analytics_lesson_and_topic_counts(analytics_setup):
    session, app = analytics_setup[0], analytics_setup[1]
    stats = app._compute_search_analytics(session)
    assert stats.total_lessons_generated == 3  # 2 diabetes levels + 1 asthma
    assert stats.total_unique_topics == 2  # diabetes, asthma
    assert stats.level_distribution == {"general_public": 2, "child": 1}


def test_search_analytics_topic_popularity_ranking(analytics_setup):
    session, app = analytics_setup[0], analytics_setup[1]
    stats = app._compute_search_analytics(session)
    diabetes = next(t for t in stats.top_topics if t.topic == "diabetes")
    assert diabetes.search_count == 2  # generated at 2 levels
    assert diabetes.view_count == 2  # u1 and u2 both viewed diabetes_general


def test_quiz_analytics_attempts_and_average(analytics_setup):
    session, app = analytics_setup[0], analytics_setup[1]
    stats = app._compute_quiz_analytics(session)
    assert stats.total_attempts == 3  # 2 + 0 + 1
    assert stats.total_lessons_with_attempts == 2  # h1 and h3 have attempts > 0, h2 doesn't
    assert stats.average_score == pytest.approx(0.9)  # (0.8 + 1.0) / 2


def test_quiz_analytics_completion_rate(analytics_setup):
    session, app = analytics_setup[0], analytics_setup[1]
    stats = app._compute_quiz_analytics(session)
    # 3 history rows total (h1, h2, h3), 2 completed (h1, h3)
    assert stats.completion_rate == pytest.approx(2 / 3)


def test_tutor_analytics_question_counts_and_split(analytics_setup):
    session, app = analytics_setup[0], analytics_setup[1]
    stats = app._compute_tutor_analytics(session)
    assert stats.total_questions == 2  # 1 signed-in + 1 anonymous (role='user' messages only)
    assert stats.lessons_with_tutor_activity == 2
    assert stats.anonymous_question_count == 1
    assert stats.signed_in_question_count == 1


def test_platform_analytics_endpoint_combines_everything(analytics_setup):
    session, app, u1, u2, u3, diabetes_general, diabetes_child, asthma_lesson = analytics_setup
    result = asyncio.run(app.get_platform_analytics(db=session, _admin=u3))

    assert result.users.total_users == 3
    assert result.search.total_lessons_generated == 3
    assert result.quiz.total_attempts == 3
    assert result.tutor.total_questions == 2
    assert result.safety_flag_count == 0  # none of the seeded lessons have safety_flags


def test_platform_analytics_route_is_gated_by_require_role_admin(analytics_setup):
    """get_platform_analytics itself has no internal role check - access
    control is enforced entirely by FastAPI resolving
    Depends(require_role(UserRole.admin)) at request time, which is
    bypassed when calling the route function directly with a manually
    substituted argument (as the rest of this file's tests correctly do,
    since they're testing the analytics COMPUTATION, not access control).
    So the right way to test the actual enforcement is the same way
    test_admin.py does: call the require_role gate function itself."""
    session, app, u1, u2, u3, *_ = analytics_setup
    admin_gate = app.require_role(app.UserRole.admin)

    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(admin_gate(user=u1))  # u1 is a student
    assert exc_info.value.status_code == 403

    result = asyncio.run(admin_gate(user=u3))  # u3 is admin
    assert result.email == "admin@x.com"
