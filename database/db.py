import os
import sqlite3

from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "spendly.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS expense_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            name        TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id),
            template_id     INTEGER NOT NULL REFERENCES expense_templates(id),
            frequency       TEXT    NOT NULL,
            next_run_date   TEXT    NOT NULL,
            description     TEXT,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def create_user(name, email, password):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash(password)),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def create_expense(user_id, amount, category, date, description):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, date, description or None),
    )
    conn.commit()
    expense_id = cursor.lastrowid
    conn.close()
    return expense_id


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return user


def get_user_row_by_id(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, email, password_hash FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row


def get_user_by_email_for_update(email, exclude_user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, email FROM users WHERE email = ? AND id != ?",
        (email, exclude_user_id),
    ).fetchone()
    conn.close()
    return row


def update_user_profile(user_id, name, email):
    conn = get_db()
    conn.execute(
        "UPDATE users SET name = ?, email = ? WHERE id = ?",
        (name, email, user_id),
    )
    conn.commit()
    conn.close()


def update_user_password(user_id, new_password):
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()
    conn.close()


def seed_db():
    conn = get_db()

    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    if row[0] > 0:
        conn.close()
        return

    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
    )
    user_id = cursor.lastrowid

    expenses = [
        (user_id, 450.00,  "Food",          "2026-04-01", "Groceries from D-Mart"),
        (user_id, 120.00,  "Transport",     "2026-04-02", "Metro card recharge"),
        (user_id, 1200.00, "Bills",         "2026-04-03", "Electricity bill"),
        (user_id, 350.00,  "Health",        "2026-04-05", "Pharmacy — vitamins"),
        (user_id, 500.00,  "Entertainment", "2026-04-06", "Movie tickets"),
        (user_id, 800.00,  "Shopping",      "2026-04-07", "New earphones"),
        (user_id, 200.00,  "Other",         "2026-04-08", "Miscellaneous"),
        (user_id, 180.00,  "Food",          "2026-04-08", "Lunch with colleagues"),
    ]

    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()


def _advance_date(date_str, frequency):
    from datetime import datetime, timedelta
    import calendar

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if frequency == "daily":
        dt += timedelta(days=1)
    elif frequency == "weekly":
        dt += timedelta(weeks=1)
    elif frequency == "monthly":
        m = dt.month + 1
        y = dt.year
        if m > 12:
            m = 1
            y += 1
        last_day = calendar.monthrange(y, m)[1]
        dt = dt.replace(year=y, month=m, day=min(dt.day, last_day))
    return dt.strftime("%Y-%m-%d")


# ------------------------------------------------------------------ #
# Template helpers                                                    #
# ------------------------------------------------------------------ #

def create_template(user_id, name, amount, category, description):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO expense_templates (user_id, name, amount, category, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, name, amount, category, description or None),
    )
    conn.commit()
    template_id = cursor.lastrowid
    conn.close()
    return template_id


def get_templates_for_user(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, user_id, name, amount, category, description, created_at "
        "FROM expense_templates WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_template_by_id(template_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, user_id, name, amount, category, description, created_at "
        "FROM expense_templates WHERE id = ? AND user_id = ?",
        (template_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_template(template_id, user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM expense_templates WHERE id = ? AND user_id = ?",
        (template_id, user_id),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ #
# Recurring helpers                                                   #
# ------------------------------------------------------------------ #

def create_recurring(user_id, template_id, frequency, next_run_date, description):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO recurring_expenses "
        "(user_id, template_id, frequency, next_run_date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, template_id, frequency, next_run_date, description or None),
    )
    conn.commit()
    recurring_id = cursor.lastrowid
    conn.close()
    return recurring_id


def get_recurring_for_user(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT r.id, r.user_id, r.template_id, r.frequency, r.next_run_date, "
        "       r.description, r.is_active, r.created_at, "
        "       t.name AS template_name, t.amount, t.category "
        "FROM recurring_expenses r "
        "JOIN expense_templates t ON t.id = r.template_id "
        "WHERE r.user_id = ? "
        "ORDER BY r.next_run_date ASC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_recurring_by_id(rec_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT r.id, r.user_id, r.template_id, r.frequency, r.next_run_date, "
        "       r.description, r.is_active, r.created_at, "
        "       t.name AS template_name, t.amount, t.category "
        "FROM recurring_expenses r "
        "JOIN expense_templates t ON t.id = r.template_id "
        "WHERE r.id = ? AND r.user_id = ?",
        (rec_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_due_recurring(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT r.id, r.template_id, r.frequency, r.description, "
        "       t.name, t.amount, t.category "
        "FROM recurring_expenses r "
        "JOIN expense_templates t ON t.id = r.template_id "
        "WHERE r.user_id = ? AND r.is_active = 1 "
        "  AND r.next_run_date <= date('now')",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def advance_recurring(rec_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT frequency, next_run_date FROM recurring_expenses "
        "WHERE id = ? AND user_id = ?",
        (rec_id, user_id),
    ).fetchone()
    if row:
        new_date = _advance_date(row["next_run_date"], row["frequency"])
        conn.execute(
            "UPDATE recurring_expenses SET next_run_date = ? WHERE id = ? AND user_id = ?",
            (new_date, rec_id, user_id),
        )
        conn.commit()
    conn.close()


def update_recurring_next_date(rec_id, user_id, new_date):
    conn = get_db()
    conn.execute(
        "UPDATE recurring_expenses SET next_run_date = ? WHERE id = ? AND user_id = ?",
        (new_date, rec_id, user_id),
    )
    conn.commit()
    conn.close()


def toggle_recurring(rec_id, user_id):
    conn = get_db()
    conn.execute(
        "UPDATE recurring_expenses "
        "SET is_active = 1 - is_active "
        "WHERE id = ? AND user_id = ?",
        (rec_id, user_id),
    )
    conn.commit()
    conn.close()


def delete_recurring(rec_id, user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM recurring_expenses WHERE id = ? AND user_id = ?",
        (rec_id, user_id),
    )
    conn.commit()
    conn.close()
