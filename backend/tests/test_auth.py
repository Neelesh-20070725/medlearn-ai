"""
Tests for password hashing, JWT issuance/verification, and the
get_current_user / require_role dependencies (main.py section 4).
"""
import asyncio
import uuid

import pytest

from conftest import make_users_table


def test_password_hash_verifies_correct_password(app):
    hashed = app.hash_password("correct-horse-battery-staple")
    assert app.verify_password("correct-horse-battery-staple", hashed)


def test_password_hash_rejects_wrong_password(app):
    hashed = app.hash_password("correct-horse-battery-staple")
    assert not app.verify_password("wrong-password", hashed)


def test_access_token_round_trips_correctly(app):
    user_id = str(uuid.uuid4())
    token = app.create_access_token(user_id, "student")
    payload = app.decode_token(token, expected_type="access")
    assert payload["sub"] == user_id
    assert payload["role"] == "student"


def test_refresh_token_cannot_be_used_as_access_token(app):
    """Type separation matters: a refresh token must never work at a
    route expecting an access token, or a long-lived token effectively
    becomes as powerful as a short-lived one."""
    user_id = str(uuid.uuid4())
    refresh = app.create_refresh_token(user_id, "student")
    with pytest.raises(app.InvalidTokenError):
        app.decode_token(refresh, expected_type="access")


def test_decode_token_rejects_garbage(app):
    with pytest.raises(app.InvalidTokenError):
        app.decode_token("not-a-real-token", expected_type="access")


def test_get_current_user_resolves_valid_token(db_session, app):
    session, engine = db_session
    users_table = make_users_table()
    users_table.metadata.create_all(engine)
    app.User.__table__ = users_table

    user = app.User(email="student@example.com", hashed_password=app.hash_password("pw"), role="student")
    session.add(user)
    session.commit()
    session.refresh(user)

    token = app.create_access_token(str(user.id), user.role)

    class FakeCreds:
        credentials = token

    resolved = asyncio.run(app.get_current_user(credentials=FakeCreds(), db=session))
    assert resolved.email == "student@example.com"


def test_get_current_user_rejects_missing_credentials(db_session, app):
    session, engine = db_session
    users_table = make_users_table()
    users_table.metadata.create_all(engine)
    app.User.__table__ = users_table

    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.get_current_user(credentials=None, db=session))
    assert exc_info.value.status_code == 401


def test_get_current_user_blocks_deactivated_account(db_session, app):
    """Deactivation must be enforced at token verification time, not just
    at login - a token issued before deactivation should stop working
    immediately, not remain valid until it expires naturally."""
    session, engine = db_session
    users_table = make_users_table()
    users_table.metadata.create_all(engine)
    app.User.__table__ = users_table

    user = app.User(email="student@example.com", hashed_password=app.hash_password("pw"), role="student", is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)

    token = app.create_access_token(str(user.id), user.role)

    user.is_active = False
    session.commit()

    class FakeCreds:
        credentials = token

    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(app.get_current_user(credentials=FakeCreds(), db=session))
    assert exc_info.value.status_code == 401


def test_require_role_blocks_wrong_role(app):
    admin_gate = app.require_role(app.UserRole.admin)
    student = app.User(email="s@x.com", hashed_password="h", role="student")
    with pytest.raises(app.HTTPException) as exc_info:
        asyncio.run(admin_gate(user=student))
    assert exc_info.value.status_code == 403


def test_require_role_allows_correct_role(app):
    admin_gate = app.require_role(app.UserRole.admin)
    admin = app.User(email="a@x.com", hashed_password="h", role="admin")
    result = asyncio.run(admin_gate(user=admin))
    assert result.email == "a@x.com"
