"""
Tests for the Medical Knowledge Service: curated topic taxonomy browsing
(public) and management (admin-only), including audit logging on mutations.
"""
import asyncio
import uuid

import pytest
import sqlalchemy as sa

from conftest import make_audit_logs_table, make_users_table


def make_topic_taxonomy_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "topic_taxonomy", metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("canonical_name", sa.String, unique=True, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("synonyms", sa.JSON, nullable=False, default=list),
        sa.Column("related_topics", sa.JSON, nullable=False, default=list),
        sa.Column("created_at", sa.DateTime),
    )


@pytest.fixture
def knowledge_setup(db_session, app):
    session, engine = db_session
    users_table = make_users_table()
    taxonomy_table = make_topic_taxonomy_table()
    audit_table = make_audit_logs_table()
    for t in (users_table, taxonomy_table, audit_table):
        t.metadata.create_all(engine)
    app.User.__table__ = users_table
    app.TopicTaxonomy.__table__ = taxonomy_table
    app.AuditLog.__table__ = audit_table

    admin = app.User(email="admin@example.com", hashed_password="h", role="admin")
    student = app.User(email="student@example.com", hashed_password="h", role="student")
    session.add_all([admin, student])
    session.commit()

    return session, app, admin, student


def test_create_taxonomy_topic(knowledge_setup):
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(
        canonical_name="Diabetes", category="endocrine",
        synonyms=["type 2 diabetes", "sugar disease"], related_topics=["Obesity"],
    )
    entry = asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))
    assert entry.canonical_name == "Diabetes"
    assert entry.category == "endocrine"
    assert "sugar disease" in entry.synonyms


def test_create_duplicate_canonical_name_rejected(knowledge_setup):
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(canonical_name="Diabetes", category="endocrine")
    asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))
    assert exc_info.value.status_code == 400


def test_create_writes_audit_entry(knowledge_setup):
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(canonical_name="Asthma", category="respiratory")
    asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    logs = asyncio.run(app.admin_get_audit_log(action="taxonomy.created", target_type=None, limit=100, db=session, _admin=admin))
    assert len(logs) == 1
    assert logs[0].target_id == "Asthma"


def test_list_topics_by_category(knowledge_setup):
    session, app, admin, student = knowledge_setup
    for name, cat in [("Diabetes", "endocrine"), ("Asthma", "respiratory"), ("Thyroid Disease", "endocrine")]:
        req = app.TaxonomyEntryCreateRequest(canonical_name=name, category=cat)
        asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    endocrine = asyncio.run(app.list_taxonomy_topics(category="endocrine", q=None, limit=50, db=session))
    assert {e.canonical_name for e in endocrine} == {"Diabetes", "Thyroid Disease"}


def test_search_matches_synonym_not_just_canonical_name(knowledge_setup):
    """A reader searching a common name, not the canonical one, must still
    find the entry - this is the whole point of storing synonyms."""
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(canonical_name="Diabetes", category="endocrine", synonyms=["sugar disease"])
    asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    results = asyncio.run(app.list_taxonomy_topics(category=None, q="sugar", limit=50, db=session))
    assert len(results) == 1
    assert results[0].canonical_name == "Diabetes"


def test_search_is_case_insensitive(knowledge_setup):
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(canonical_name="Diabetes", category="endocrine")
    asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    results = asyncio.run(app.list_taxonomy_topics(category=None, q="DIABE", limit=50, db=session))
    assert len(results) == 1


def test_list_categories_returns_distinct_sorted(knowledge_setup):
    session, app, admin, student = knowledge_setup
    for name, cat in [("Diabetes", "endocrine"), ("Thyroid Disease", "endocrine"), ("Asthma", "respiratory")]:
        req = app.TaxonomyEntryCreateRequest(canonical_name=name, category=cat)
        asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    categories = asyncio.run(app.list_taxonomy_categories(db=session))
    assert categories == ["endocrine", "respiratory"]


def test_update_taxonomy_topic(knowledge_setup):
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(canonical_name="Diabetes", category="endocrine")
    entry = asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    update_req = app.TaxonomyEntryUpdateRequest(synonyms=["diabetes mellitus"])
    updated = asyncio.run(app.admin_update_taxonomy_topic(entry.id, update_req, db=session, admin=admin))
    assert updated.synonyms == ["diabetes mellitus"]
    assert updated.category == "endocrine"  # unchanged fields stay as they were


def test_update_nonexistent_topic_404s(knowledge_setup):
    session, app, admin, student = knowledge_setup
    update_req = app.TaxonomyEntryUpdateRequest(category="new_category")
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.admin_update_taxonomy_topic(str(uuid.uuid4()), update_req, db=session, admin=admin))
    assert exc_info.value.status_code == 404


def test_delete_taxonomy_topic(knowledge_setup):
    session, app, admin, student = knowledge_setup
    req = app.TaxonomyEntryCreateRequest(canonical_name="Diabetes", category="endocrine")
    entry = asyncio.run(app.admin_create_taxonomy_topic(req, db=session, admin=admin))

    asyncio.run(app.admin_delete_taxonomy_topic(entry.id, db=session, admin=admin))
    remaining = asyncio.run(app.list_taxonomy_topics(category=None, q=None, limit=50, db=session))
    assert remaining == []


def test_management_endpoints_require_admin_role(knowledge_setup):
    """The route-level Depends(require_role(admin)) is what actually
    enforces this - tested via the gate function itself, the same
    correct pattern used for every other admin-only route in this
    project (calling the route function directly bypasses FastAPI's
    dependency resolution entirely)."""
    session, app, admin, student = knowledge_setup
    admin_gate = app.require_role(app.UserRole.admin)
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(admin_gate(user=student))
    assert exc_info.value.status_code == 403
