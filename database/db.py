import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_NAME = "spendly.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def seed_db():
    conn = get_db()
    try:
        existing = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()
        if existing["count"] > 0:
            return

        password_hash = generate_password_hash("demo123")
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", password_hash)
        )
        user_id = cursor.lastrowid

        import datetime
        today = datetime.date.today()
        expenses = [
            (user_id, 45.50, "Food", str(today.replace(day=1)), "Coffee and breakfast"),
            (user_id, 120.00, "Transport", str(today.replace(day=3)), "Uber rides"),
            (user_id, 85.00, "Bills", str(today.replace(day=5)), "Electricity bill"),
            (user_id, 30.00, "Health", str(today.replace(day=7)), "Pharmacy"),
            (user_id, 55.00, "Entertainment", str(today.replace(day=10)), "Movie tickets"),
            (user_id, 200.00, "Shopping", str(today.replace(day=12)), "Clothes"),
            (user_id, 25.00, "Other", str(today.replace(day=15)), "Miscellaneous"),
            (user_id, 65.00, "Food", str(today.replace(day=18)), "Grocery shopping"),
        ]

        for expense in expenses:
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
                expense
            )

        conn.commit()
    finally:
        conn.close()