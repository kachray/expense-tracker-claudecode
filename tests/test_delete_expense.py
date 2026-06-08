# tests/test_delete_expense.py
#
# Spec: Step 9 — Delete Expense
#
# Behaviors under test:
#
#  1. Auth guard: unauthenticated POST /expenses/<id>/delete redirects to /login
#  2. POST own expense: 302 redirect to /profile, expense removed from DB
#  3. POST non-existent expense: 404
#  4. POST other user's expense: 404, row unchanged
#  5. GET /expenses/<id>/delete: 405 Method Not Allowed
#  6. Unit: delete_expense removes row for correct user
#  7. Unit: delete_expense is no-op for wrong user
#  8. Unit: delete_expense is no-op for non-existent id

import os
import tempfile

from datetime import date

import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# Isolated temp DB setup
# ---------------------------------------------------------------------------
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["SPENDLY_TEST_DB"] = _tmp_db.name

import database.db as _db_module
_db_module.DB_PATH = _tmp_db.name

from app import app
from database.db import get_db, init_db
from database.queries import delete_expense, get_expense_by_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
TODAY_STR = TODAY.isoformat()


def _setup_db():
    """Create tables and two test users with their own expenses."""
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

    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_a_id, 100.00, "Food", TODAY_STR, "Lunch"),
    )
    expense_a_id = cursor.lastrowid

    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_b_id, 500.00, "Shopping", TODAY_STR, "Headphones"),
    )
    expense_b_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return user_a_id, expense_a_id, user_b_id, expense_b_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as c:
        with app.app_context():
            user_a_id, expense_a_id, user_b_id, expense_b_id = _setup_db()
        yield c, user_a_id, expense_a_id, user_b_id, expense_b_id

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


def _login_user_b(c):
    return _login(c, email="userb@spendly.com")


# ---------------------------------------------------------------------------
# Unit tests — delete_expense
# ---------------------------------------------------------------------------

class TestDeleteExpenseUnit:
    def test_delete_expense_removes_row_for_correct_user(self, client):
        _, user_a_id, expense_a_id, _, _ = client
        with app.app_context():
            delete_expense(expense_a_id, user_a_id)
            remaining = get_expense_by_id(expense_a_id, user_a_id)
        assert remaining is None

    def test_delete_expense_no_effect_for_wrong_user(self, client):
        _, user_a_id, expense_a_id, user_b_id, _ = client
        with app.app_context():
            delete_expense(expense_a_id, user_b_id)  # User B tries to delete A's expense
            remaining = get_expense_by_id(expense_a_id, user_a_id)
        assert remaining is not None  # Row is untouched
        assert remaining["amount"] == 100.00

    def test_delete_expense_no_effect_for_non_existent_id(self, client):
        _, user_a_id, _, _, _ = client
        with app.app_context():
            # Should not raise
            delete_expense(99999, user_a_id)


# ---------------------------------------------------------------------------
# Route tests — POST /expenses/<id>/delete
# ---------------------------------------------------------------------------

class TestPostDeleteExpense:
    def test_unauthenticated_post_redirects_to_login(self, client):
        c, _, expense_a_id, _, _ = client
        response = c.post(f"/expenses/{expense_a_id}/delete", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_authenticated_own_expense_redirects_to_profile(self, client):
        c, user_a_id, expense_a_id, _, _ = client
        _login(c)
        response = c.post(f"/expenses/{expense_a_id}/delete", follow_redirects=False)
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_authenticated_own_expense_flash_success(self, client):
        c, user_a_id, expense_a_id, _, _ = client
        _login(c)
        response = c.post(f"/expenses/{expense_a_id}/delete", follow_redirects=True)
        body = response.data.decode()
        assert "deleted" in body.lower() or "success" in body.lower()

    def test_authenticated_own_expense_removes_from_db(self, client):
        c, user_a_id, expense_a_id, _, _ = client
        _login(c)
        c.post(f"/expenses/{expense_a_id}/delete", follow_redirects=True)
        with app.app_context():
            remaining = get_expense_by_id(expense_a_id, user_a_id)
        assert remaining is None

    def test_authenticated_non_existent_expense_returns_404(self, client):
        c, user_a_id, _, _, _ = client
        _login(c)
        response = c.post("/expenses/99999/delete", follow_redirects=False)
        assert response.status_code == 404

    def test_authenticated_other_user_expense_returns_404(self, client):
        c, user_a_id, _, _, expense_b_id = client
        _login(c)
        response = c.post(f"/expenses/{expense_b_id}/delete", follow_redirects=False)
        assert response.status_code == 404

    def test_authenticated_other_user_expense_row_unchanged(self, client):
        c, user_a_id, _, user_b_id, expense_b_id = client
        _login(c)
        c.post(f"/expenses/{expense_b_id}/delete", follow_redirects=True)
        with app.app_context():
            remaining = get_expense_by_id(expense_b_id, user_b_id)
        assert remaining is not None  # User B's row is intact


# ---------------------------------------------------------------------------
# Route tests — GET /expenses/<id>/delete (must return 405)
# ---------------------------------------------------------------------------

class TestGetDeleteExpense:
    def test_get_returns_405(self, client):
        c, user_a_id, expense_a_id, _, _ = client
        _login(c)
        response = c.get(f"/expenses/{expense_a_id}/delete", follow_redirects=False)
        assert response.status_code == 405

    def test_get_unauthenticated_returns_405(self, client):
        c, _, expense_a_id, _, _ = client
        response = c.get(f"/expenses/{expense_a_id}/delete", follow_redirects=False)
        assert response.status_code == 405