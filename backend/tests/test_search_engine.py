"""
Tests for autocomplete and popular-searches (main.py's Search Engine
routes), both derived from LessonRecord.topic.
"""
import asyncio

from conftest import make_lessons_table


def _make_lesson(app, session, topic, level):
    lesson = app.Lesson(
        topic=topic, level=level,
        sections=[{"id": "s", "title": "T", "content": "c", "sources": []}],
        quiz=[],
    )
    record = app.LessonRecord(topic=topic, level=level, content=lesson.model_dump(mode="json"), model_versions={}, safety_flags=[])
    session.add(record)
    session.commit()
    return record


def test_autocomplete_matches_multiple_topics_sharing_prefix(db_session, app):
    session, engine = db_session
    lessons_table = make_lessons_table()
    lessons_table.metadata.create_all(engine)
    app.LessonRecord.__table__ = lessons_table

    _make_lesson(app, session, "diabetes", "general_public")
    _make_lesson(app, session, "diabetes", "child")
    _make_lesson(app, session, "diarrhea", "general_public")

    results = asyncio.run(app.search_autocomplete(q="dia", limit=8, db=session))
    topics = {r.topic for r in results}
    assert topics == {"diabetes", "diarrhea"}


def test_autocomplete_ranks_by_level_count(db_session, app):
    session, engine = db_session
    lessons_table = make_lessons_table()
    lessons_table.metadata.create_all(engine)
    app.LessonRecord.__table__ = lessons_table

    _make_lesson(app, session, "diabetes", "general_public")
    _make_lesson(app, session, "diabetes", "child")
    _make_lesson(app, session, "diabetes", "medical_student")
    _make_lesson(app, session, "diarrhea", "general_public")

    results = asyncio.run(app.search_autocomplete(q="dia", limit=8, db=session))
    diabetes_result = next(r for r in results if r.topic == "diabetes")
    assert diabetes_result.level_count == 3
    assert results[0].topic == "diabetes"  # ranked above diarrhea (1 level)


def test_autocomplete_rejects_too_short_prefix(db_session, app):
    session, engine = db_session
    lessons_table = make_lessons_table()
    lessons_table.metadata.create_all(engine)
    app.LessonRecord.__table__ = lessons_table

    _make_lesson(app, session, "diabetes", "general_public")

    results = asyncio.run(app.search_autocomplete(q="d", limit=8, db=session))
    assert results == []


def test_autocomplete_no_match_returns_empty_not_error(db_session, app):
    session, engine = db_session
    lessons_table = make_lessons_table()
    lessons_table.metadata.create_all(engine)
    app.LessonRecord.__table__ = lessons_table

    _make_lesson(app, session, "diabetes", "general_public")

    results = asyncio.run(app.search_autocomplete(q="xyz123", limit=8, db=session))
    assert results == []


def test_popular_searches_ordered_by_count(db_session, app):
    session, engine = db_session
    lessons_table = make_lessons_table()
    lessons_table.metadata.create_all(engine)
    app.LessonRecord.__table__ = lessons_table

    for level in ("general_public", "child", "medical_student"):
        _make_lesson(app, session, "diabetes", level)
    for level in ("general_public", "child"):
        _make_lesson(app, session, "asthma", level)
    _make_lesson(app, session, "diarrhea", "general_public")

    popular = asyncio.run(app.search_popular(limit=10, db=session))
    assert [p.topic for p in popular] == ["diabetes", "asthma", "diarrhea"]
    assert popular[0].search_count == 3
    assert popular[1].search_count == 2
