# tests/test_edit_profile.py
#
# Spec: Step 12 — Edit Profile
#
# Behaviors under test:
#
#  1. Auth guard: unauthenticated GET/POST /profile/edit redirects to /login
#  2. GET authenticated: 200, form pre-populated with current name/email
#  3. POST happy path (name+email only): 302 to /profile, DB updated, /profile reflects
#  4. POST happy path (password change): new password authenticates, old password fails
#  5. POST wrong current password: re-render, no DB change
#  6. POST empty name: re-render + flash
#  7. POST malformed email: re-render + flash
#  8. POST email colliding with another user: re-render + flash, no DB change
#  9. POST keeping own email unchanged: 302, no false duplicate error
# 10. POST password mismatch: re-render + flash, no DB change
# 11. POST password too short: re-render + flash
# 12. POST with blank new_password: keeps old password (login still works)
# 13. Unit: password hash starts with a werkzeug scheme prefix after update
# 14. Profile page shows an Edit Profile link to /profile/edit
# 15. Unit: get_user_by_email_for_update excludes self
# 16. Unit: update_user_profile and update_user_password mutate the row
# 17. Unit: get_user_row_by_id returns the password_hash field

import os
import tempfile

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Isolated temp DB setup
# ---------------------------------------------------------------------------
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["SPENDLY_TEST_DB"] = _tmp_db.name

import database.db as _db_module
_db_module.DB_PATH = _tmp_db.name

from app import app
from database.db import (
    get_db,
    get_user_by_email_for_update,
    get_user_row_by_id,
    init_db,
    update_user_password,
    update_user_profile,
)

NEW_PASSWORD = "newpass1234"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db():
    """Create tables and two test users."""
    init_db()
    conn = get_db()
    conn.execute("DELETE FROM expenses")
    conn.execute("DELETE FROM users")
    conn.commit()

    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("User A", "usera@spendly.com", generate_password_hash("password123")),
    )
    user_a_id = cursor.lastrowid

    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("User B", "userb@spendly.com", generate_password_hash("password123")),
    )
    user_b_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return user_a_id, user_b_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as c:
        with app.app_context():
            user_a_id, user_b_id = _setup_db()
        yield c, user_a_id, user_b_id

    with app.app_context():
        conn = get_db()
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM users")
        conn.commit()
        conn.close()


def _login(c, email="usera@spendly.com", password="password123"):
    return c.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Unit tests — DB helpers
# ---------------------------------------------------------------------------

class TestGetUserByEmailForUpdate:
    def test_excludes_self_returns_none(self, client):
        _, user_a_id, _ = client
        with app.app_context():
            row = get_user_by_email_for_update("usera@spendly.com", user_a_id)
        assert row is None

    def test_returns_other_user(self, client):
        _, user_a_id, user_b_id = client
        with app.app_context():
            row = get_user_by_email_for_update("userb@spendly.com", user_a_id)
        assert row is not None
        assert row["id"] == user_b_id
        assert row["email"] == "userb@spendly.com"

    def test_returns_none_for_nonexistent_email(self, client):
        _, user_a_id, _ = client
        with app.app_context():
            row = get_user_by_email_for_update("nobody@spendly.com", user_a_id)
        assert row is None


class TestGetUserRowById:
    def test_returns_row_with_password_hash(self, client):
        _, user_a_id, _ = client
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert row is not None
        assert row["name"] == "User A"
        assert row["email"] == "usera@spendly.com"
        assert "password_hash" in row.keys()
        assert check_password_hash(row["password_hash"], "password123")

    def test_returns_none_for_missing_id(self, client):
        with app.app_context():
            row = get_user_row_by_id(99999)
        assert row is None


class TestUpdateUserProfile:
    def test_writes_name_and_email(self, client):
        _, user_a_id, _ = client
        with app.app_context():
            update_user_profile(user_a_id, "Renamed A", "renamed@spendly.com")
            row = get_user_row_by_id(user_a_id)
        assert row["name"] == "Renamed A"
        assert row["email"] == "renamed@spendly.com"


class TestUpdateUserPassword:
    def test_writes_new_hash_with_werkzeug_prefix(self, client):
        _, user_a_id, _ = client
        with app.app_context():
            update_user_password(user_a_id, NEW_PASSWORD)
            row = get_user_row_by_id(user_a_id)
        hash_value = row["password_hash"]
        # Any modern werkzeug hash starts with one of these schemes.
        assert hash_value.startswith("pbkdf2:") or hash_value.startswith("scrypt:")
        assert check_password_hash(hash_value, NEW_PASSWORD)
        # Old password no longer authenticates
        assert not check_password_hash(hash_value, "password123")


# ---------------------------------------------------------------------------
# Route tests — GET /profile/edit
# ---------------------------------------------------------------------------

class TestGetEditProfile:
    def test_unauthenticated_get_redirects_to_login(self, client):
        c, _, _ = client
        response = c.get("/profile/edit", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_authenticated_get_returns_200(self, client):
        c, _, _ = client
        _login(c)
        response = c.get("/profile/edit")
        assert response.status_code == 200

    def test_authenticated_get_prefilled_with_name_and_email(self, client):
        c, _, _ = client
        _login(c)
        body = c.get("/profile/edit").data.decode()
        assert 'value="User A"' in body
        assert 'value="usera@spendly.com"' in body

    def test_authenticated_get_does_not_prefill_current_password(self, client):
        """Security: the current password field must NOT echo back data."""
        c, _, _ = client
        _login(c)
        body = c.get("/profile/edit").data.decode()
        # The current_password input should be present but value-less/random.
        # It must never contain "password123" anywhere near the password inputs.
        assert "password123" not in body


# ---------------------------------------------------------------------------
# Route tests — POST /profile/edit
# ---------------------------------------------------------------------------

class TestPostEditProfile:
    def test_unauthenticated_post_redirects_to_login(self, client):
        c, _, _ = client
        response = c.post(
            "/profile/edit",
            data={
                "name": "Hacker",
                "email": "hacker@spendly.com",
                "current_password": "wrong",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_valid_name_email_update_redirects_to_profile(self, client):
        c, _, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "password123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_valid_update_flashes_success(self, client):
        c, _, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "password123",
            },
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "updated" in body.lower() or "success" in body.lower()

    def test_valid_update_persists_to_db(self, client):
        c, user_a_id, _ = client
        _login(c)
        c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "password123",
            },
            follow_redirects=True,
        )
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert row["name"] == "Renamed A"
        assert row["email"] == "renamed@spendly.com"

    def test_valid_update_propagates_to_profile_page(self, client):
        c, _, _ = client
        _login(c)
        c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "password123",
            },
            follow_redirects=True,
        )
        profile_body = c.get("/profile").data.decode()
        assert "Renamed A" in profile_body
        assert "renamed@spendly.com" in profile_body

    def test_password_change_updates_hash_and_old_password_fails(self, client):
        c, user_a_id, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "usera@spendly.com",
                "current_password": "password123",
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert check_password_hash(row["password_hash"], NEW_PASSWORD)
        assert not check_password_hash(row["password_hash"], "password123")

    def test_password_change_allows_login_with_new_password(self, client):
        c, _, _ = client
        # First login with old password
        _login(c)
        # Change the password
        c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "usera@spendly.com",
                "current_password": "password123",
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=True,
        )
        # Logout via /logout (clears session) and try logging in with new password
        c.get("/logout", follow_redirects=True)
        response = c.post(
            "/login",
            data={"email": "usera@spendly.com", "password": NEW_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_wrong_current_password_rerenders(self, client):
        c, _, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "wrongpw",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_wrong_current_password_does_not_mutate_db(self, client):
        c, user_a_id, _ = client
        _login(c)
        c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "wrongpw",
            },
            follow_redirects=True,
        )
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        # Should still be the original name/email
        assert row["name"] == "User A"
        assert row["email"] == "usera@spendly.com"

    def test_wrong_current_password_shows_error(self, client):
        c, _, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "wrongpw",
            },
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "incorrect" in body.lower() or "current password" in body.lower()

    def test_empty_name_rerenders_with_error(self, client):
        c, user_a_id, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "",
                "email": "usera@spendly.com",
                "current_password": "password123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200
        body = response.data.decode()
        assert "name" in body.lower() and "required" in body.lower()
        # And no DB mutation
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert row["name"] == "User A"

    def test_malformed_email_rerenders_with_error(self, client):
        c, user_a_id, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "not-an-email",
                "current_password": "password123",
            },
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "valid" in body.lower() and "email" in body.lower()
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert row["email"] == "usera@spendly.com"

    def test_duplicate_email_other_user_rejects(self, client):
        c, user_a_id, _ = client
        _login(c)  # logged in as user A
        response = c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "userb@spendly.com",  # already used by B
                "current_password": "password123",
            },
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "already" in body.lower() or "registered" in body.lower()
        # A's row unchanged
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert row["email"] == "usera@spendly.com"

    def test_keeping_own_email_succeeds_and_does_not_error(self, client):
        c, user_a_id, user_b_id = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "usera@spendly.com",  # same as current
                "current_password": "password123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]
        # User B is unmolested
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
            assert row["email"] == "usera@spendly.com"
            assert user_b_id is not None

    def test_password_mismatch_rerenders_with_error(self, client):
        c, user_a_id, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "usera@spendly.com",
                "current_password": "password123",
                "new_password": NEW_PASSWORD,
                "confirm_password": "different_password",
            },
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "match" in body.lower() or "do not" in body.lower()
        # Password not changed
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert check_password_hash(row["password_hash"], "password123")
        assert not check_password_hash(row["password_hash"], NEW_PASSWORD)

    def test_password_too_short_rerenders_with_error(self, client):
        c, user_a_id, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "User A",
                "email": "usera@spendly.com",
                "current_password": "password123",
                "new_password": "short",
                "confirm_password": "short",
            },
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "at least 6" in body.lower() or "characters" in body.lower()
        # Password not changed
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert check_password_hash(row["password_hash"], "password123")

    def test_blank_new_password_keeps_old_password(self, client):
        """Submitting name+email only (new_password blank) must not touch the hash."""
        c, user_a_id, _ = client
        _login(c)
        response = c.post(
            "/profile/edit",
            data={
                "name": "Renamed A",
                "email": "renamed@spendly.com",
                "current_password": "password123",
                "new_password": "",
                "confirm_password": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        with app.app_context():
            row = get_user_row_by_id(user_a_id)
        assert row["name"] == "Renamed A"
        assert row["email"] == "renamed@spendly.com"
        # Hash unchanged — old password still works
        assert check_password_hash(row["password_hash"], "password123")


# ---------------------------------------------------------------------------
# Integration — profile page exposes the Edit Profile link
# ---------------------------------------------------------------------------

class TestProfileEditLink:
    def test_profile_page_renders_edit_profile_link(self, client):
        c, _, _ = client
        _login(c)
        body = c.get("/profile").data.decode()
        assert "/profile/edit" in body
        assert "Edit Profile" in body
