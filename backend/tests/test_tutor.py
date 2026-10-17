"""
Tests for the AI Tutor Engine: prompt building (build_tutor_prompt), the
safety fail-closed retry logic (answer_tutor_question), and the
ask_tutor/get_tutor_history endpoints for both anonymous and signed-in
callers.
"""
import asyncio

import pytest

from conftest import make_lessons_table, make_tutor_messages_table, make_users_table


# --- Prompt building -------------------------------------------------------------

def test_tutor_prompt_includes_lesson_topic_and_question(app):
    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    prompt = app.build_tutor_prompt(lesson, [], "Why does this happen?")
    assert "Asthma" in prompt
    assert "Why does this happen?" in prompt


def test_tutor_prompt_includes_conversation_history_when_present(app):
    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    history = [{"role": "user", "content": "What is it?"}, {"role": "assistant", "content": "A lung condition."}]
    prompt = app.build_tutor_prompt(lesson, history, "Explain simpler")
    assert "A lung condition." in prompt


def test_tutor_prompt_omits_history_block_when_empty(app):
    """No stray 'Recent conversation:' header should appear for a
    first-ever question with no prior turns."""
    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    prompt = app.build_tutor_prompt(lesson, [], "What causes it?")
    assert "Recent conversation" not in prompt


# --- Safety fail-closed retry (mocked Claude client) ------------------------------

class _FakeMessageBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeMessageBlock(text)]


class _FakeMessagesAPI:
    def __init__(self, texts):
        self._texts = texts
        self._i = 0

    def create(self, **kwargs):
        text = self._texts[min(self._i, len(self._texts) - 1)]
        self._i += 1
        return _FakeMessage(text)


class _FakeAnthropicClient:
    def __init__(self, texts):
        self.messages = _FakeMessagesAPI(texts)


def test_answer_tutor_question_raises_when_repeatedly_flagged(app, monkeypatch):
    """If the model's answer contains directed diagnostic language on
    both the original attempt and the one retry, this must raise rather
    than ever serve the flagged content."""
    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    bad_answer = "You have asthma and you should take your inhaler now."
    fake_client = _FakeAnthropicClient([bad_answer, bad_answer])
    monkeypatch.setattr(app, "_anthropic_client", fake_client)

    with pytest.raises(app.UnsafeTutorAnswerError):
        asyncio.run(app.answer_tutor_question(lesson, [], "What happens if I don't treat it?"))


def test_answer_tutor_question_returns_safe_answer(app, monkeypatch):
    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    safe_answer = "This condition can worsen over time if the underlying inflammation is not managed."
    fake_client = _FakeAnthropicClient([safe_answer])
    monkeypatch.setattr(app, "_anthropic_client", fake_client)

    answer = asyncio.run(app.answer_tutor_question(lesson, [], "What happens if this isn't managed?"))
    assert "worsen" in answer


def test_answer_tutor_question_succeeds_on_retry_after_first_flag(app, monkeypatch):
    """The first draft is flagged, the retry is clean - the retry path
    itself must actually work, not just the immediate-success and
    always-fails cases."""
    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    bad_answer = "You have asthma and you should take your inhaler now."
    good_answer = "This condition is generally managed with prescribed treatment as directed by a clinician."
    fake_client = _FakeAnthropicClient([bad_answer, good_answer])
    monkeypatch.setattr(app, "_anthropic_client", fake_client)

    answer = asyncio.run(app.answer_tutor_question(lesson, [], "How is this treated?"))
    assert answer == good_answer


# --- ask_tutor / get_tutor_history endpoints --------------------------------------

@pytest.fixture
def tutor_setup(db_session, app, monkeypatch):
    session, engine = db_session
    users_table = make_users_table()
    lessons_table = make_lessons_table()
    tutor_table = make_tutor_messages_table()
    for t in (users_table, lessons_table, tutor_table):
        t.metadata.create_all(engine)
    app.User.__table__ = users_table
    app.LessonRecord.__table__ = lessons_table
    app.TutorMessage.__table__ = tutor_table

    user = app.User(email="student@example.com", hashed_password="h", role="student")
    session.add(user)
    session.commit()
    session.refresh(user)

    lesson = app.Lesson(
        topic="Asthma", level="general_public",
        sections=[{"id": "s", "title": "What is it?", "content": "Asthma is a chronic lung condition.", "sources": []}],
        quiz=[],
    )
    lesson_record = app.LessonRecord(topic="asthma", level="general_public", content=lesson.model_dump(mode="json"), model_versions={}, safety_flags=[])
    session.add(lesson_record)
    session.commit()
    session.refresh(lesson_record)

    safe_answer = "This condition is caused by airway inflammation triggered by irritants."
    fake_client = _FakeAnthropicClient([safe_answer] * 10)  # enough for several questions across tests
    monkeypatch.setattr(app, "_anthropic_client", fake_client)

    return session, app, user, lesson_record


def test_ask_tutor_anonymous_succeeds_and_persists_with_null_user(tutor_setup):
    session, app, user, lesson_record = tutor_setup
    req = app.TutorRequest(question="What causes it?")
    response = asyncio.run(app.ask_tutor(str(lesson_record.id), req, user=None, db=session))
    assert "inflammation" in response.answer

    messages = session.query(app.TutorMessage).filter(app.TutorMessage.lesson_id == lesson_record.id).all()
    assert len(messages) == 2  # user question + assistant answer
    assert all(m.user_id is None for m in messages)


def test_ask_tutor_signed_in_persists_with_user_id(tutor_setup):
    session, app, user, lesson_record = tutor_setup
    req = app.TutorRequest(question="What causes it?")
    asyncio.run(app.ask_tutor(str(lesson_record.id), req, user=user, db=session))

    messages = session.query(app.TutorMessage).filter(
        app.TutorMessage.lesson_id == lesson_record.id, app.TutorMessage.user_id == user.id
    ).all()
    assert len(messages) == 2


def test_ask_tutor_nonexistent_lesson_404s(tutor_setup):
    import uuid
    session, app, user, _ = tutor_setup
    req = app.TutorRequest(question="What causes it?")
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.ask_tutor(str(uuid.uuid4()), req, user=None, db=session))
    assert exc_info.value.status_code == 404


def test_get_tutor_history_returns_signed_in_users_conversation(tutor_setup):
    session, app, user, lesson_record = tutor_setup
    req = app.TutorRequest(question="What causes it?")
    asyncio.run(app.ask_tutor(str(lesson_record.id), req, user=user, db=session))

    history = asyncio.run(app.get_tutor_history(str(lesson_record.id), user=user, db=session))
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"


def test_anonymous_and_signed_in_conversations_are_isolated(tutor_setup):
    """An anonymous question and a signed-in question on the same lesson
    must not bleed into each other's history."""
    session, app, user, lesson_record = tutor_setup

    anon_req = app.TutorRequest(question="Anonymous question")
    asyncio.run(app.ask_tutor(str(lesson_record.id), anon_req, user=None, db=session))

    signed_in_req = app.TutorRequest(question="Signed-in question")
    asyncio.run(app.ask_tutor(str(lesson_record.id), signed_in_req, user=user, db=session))

    history = asyncio.run(app.get_tutor_history(str(lesson_record.id), user=user, db=session))
    assert len(history) == 2  # only the signed-in user's own Q+A, not the anonymous pair too
    assert history[0].content == "Signed-in question"
