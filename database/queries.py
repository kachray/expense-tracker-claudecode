from datetime import datetime, date

from database.db import (
    advance_recurring,
    create_expense,
    get_db,
    get_due_recurring,
    get_recurring_for_user,
    get_template_by_id,
    get_templates_for_user,
)


def _build_date_filter(date_from, date_to):
    if date_from and date_to:
        return "AND date BETWEEN ? AND ?", [date_from, date_to]
    return "", []


def _build_search_filter(search):
    if search:
        return "AND description LIKE '%' || ? || '%'", [search]
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


def get_expense_by_id(expense_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, user_id, amount, category, date, description "
        "FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, user_id),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def update_expense(expense_id, user_id, amount, category, date, description):
    conn = get_db()
    conn.execute(
        "UPDATE expenses SET amount=?, category=?, date=?, description=? "
        "WHERE id=? AND user_id=?",
        (amount, category, date, description, expense_id, user_id),
    )
    conn.commit()
    conn.close()


def delete_expense_record(expense_id, user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM expenses WHERE id=? AND user_id=?",
        (expense_id, user_id),
    )
    conn.commit()
    conn.close()


def delete_all_expenses_for_user(user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM expenses WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None, search=None):
    date_clause, date_params = _build_date_filter(date_from, date_to)
    search_clause, search_params = _build_search_filter(search)
    params = [user_id] + date_params + search_params + [limit]

    conn = get_db()
    rows = conn.execute(
        "SELECT id, date, description, category, amount "
        "FROM expenses "
        "WHERE user_id = ? "
        + date_clause +
        " "
        + search_clause +
        " ORDER BY date DESC, id DESC "
        "LIMIT ?",
        params,
    ).fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "date": datetime.strptime(row["date"], "%Y-%m-%d").strftime("%d %b %Y"),
            "description": row["description"],
            "category": row["category"],
            "amount": "{:,.2f}".format(row["amount"]),
        }
        for row in rows
    ]


def get_summary_stats(user_id, date_from=None, date_to=None, search=None):
    date_clause, date_params = _build_date_filter(date_from, date_to)
    search_clause, search_params = _build_search_filter(search)
    params = [user_id] + date_params + search_params

    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count "
        "FROM expenses WHERE user_id = ? "
        + date_clause +
        " "
        + search_clause,
        params,
    ).fetchone()
    total_value = row["total"]
    count = row["count"]

    cat_row = conn.execute(
        "SELECT category FROM expenses WHERE user_id = ? "
        + date_clause +
        " "
        + search_clause +
        " GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        params,
    ).fetchone()
    conn.close()

    return {
        "total": "{:,.2f}".format(total_value),
        "count": count,
        "top_category": cat_row["category"] if cat_row else "—",
    }


def get_category_breakdown(user_id, date_from=None, date_to=None, search=None):
    date_clause, date_params = _build_date_filter(date_from, date_to)
    search_clause, search_params = _build_search_filter(search)
    params = [user_id] + date_params + search_params

    conn = get_db()
    rows = conn.execute(
        "SELECT category AS name, SUM(amount) AS total "
        "FROM expenses "
        "WHERE user_id = ? "
        + date_clause +
        " "
        + search_clause +
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


def get_templates(user_id):
    rows = get_templates_for_user(user_id)
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "amount": "{:,.2f}".format(row["amount"]),
            "category": row["category"],
            "description": row["description"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_recurring_schedules(user_id):
    rows = get_recurring_for_user(user_id)
    return [
        {
            "id": row["id"],
            "template_id": row["template_id"],
            "template_name": row["name"],
            "amount": "{:,.2f}".format(row["amount"]),
            "category": row["category"],
            "frequency": row["frequency"],
            "next_run_date": row["next_run_date"],
            "description": row["description"],
            "is_active": bool(row["is_active"]),
        }
        for row in rows
    ]


def process_recurring_expenses(user_id):
    """
    Process all due recurring expenses for a user.
    Creates real expense rows and advances next_run_date.
    Returns a list of human-readable names of what was added.
    """
    due = get_due_recurring(user_id)
    if not due:
        return []

    added = []
    today = date.today().isoformat()
    for item in due:
        # description: use recurring-level override, else template name
        desc = item["description"] if item["description"] else item["name"]
        create_expense(user_id, item["amount"], item["category"], today, desc)
        # advance by recurring id (item["id"] is the recurring_expenses pk)
        advance_recurring(item["id"], user_id)
        added.append(f"{item['name']} ({item['amount']})")
    return added
