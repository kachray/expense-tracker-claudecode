from datetime import datetime

from database.db import get_db


def _build_date_filter(date_from, date_to):
    if date_from and date_to:
        return "AND date BETWEEN ? AND ?", [date_from, date_to]
    return "", []


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, email, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    name = row["name"]
    initials = "".join(w[0].upper() for w in name.split() if w)
    member_since = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%B %Y")

    return {
        "name": name,
        "email": row["email"],
        "initials": initials,
        "member_since": member_since,
    }


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    date_clause, date_params = _build_date_filter(date_from, date_to)
    params = [user_id] + date_params + [limit]

    conn = get_db()
    rows = conn.execute(
        "SELECT date, description, category, amount "
        "FROM expenses "
        "WHERE user_id = ? "
        + date_clause +
        " ORDER BY date DESC, id DESC "
        "LIMIT ?",
        params,
    ).fetchall()
    conn.close()

    return [
        {
            "date": datetime.strptime(row["date"], "%Y-%m-%d").strftime("%d %b %Y"),
            "description": row["description"],
            "category": row["category"],
            "amount": "{:,.2f}".format(row["amount"]),
        }
        for row in rows
    ]


def get_summary_stats(user_id, date_from=None, date_to=None):
    date_clause, date_params = _build_date_filter(date_from, date_to)
    params = [user_id] + date_params

    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count "
        "FROM expenses WHERE user_id = ? "
        + date_clause,
        params,
    ).fetchone()
    total_value = row["total"]
    count = row["count"]

    cat_row = conn.execute(
        "SELECT category FROM expenses WHERE user_id = ? "
        + date_clause +
        " GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        params,
    ).fetchone()
    conn.close()

    return {
        "total": "{:,.2f}".format(total_value),
        "count": count,
        "top_category": cat_row["category"] if cat_row else "—",
    }


def get_category_breakdown(user_id, date_from=None, date_to=None):
    date_clause, date_params = _build_date_filter(date_from, date_to)
    params = [user_id] + date_params

    conn = get_db()
    rows = conn.execute(
        "SELECT category AS name, SUM(amount) AS total "
        "FROM expenses "
        "WHERE user_id = ? "
        + date_clause +
        " GROUP BY category "
        "ORDER BY total DESC",
        params,
    ).fetchall()
    conn.close()

    grand_total = sum(r["total"] for r in rows)
    if grand_total == 0:
        return []

    pcts = [int(r["total"] / grand_total * 100) for r in rows]
    pcts[0] += 100 - sum(pcts)

    return [
        {
            "name": r["name"],
            "amount": "{:,.2f}".format(r["total"]),
            "percent": pct,
        }
        for r, pct in zip(rows, pcts)
    ]
