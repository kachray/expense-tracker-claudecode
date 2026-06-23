# Spec: Expense Templates and Recurring Expenses

## Overview

Two quality-of-life features that reduce friction at the point of expense entry.

**Expense templates** let a user save a favourite or common expense (e.g. "Netflix, $599, Bills") so the form pre-fills in one click instead of re-typing every week.

**Recurring expenses** extend templates with a schedule. When a user logs in, the app silently processes any recurring expenses whose `next_run_date` is today or earlier, creates real expense rows, advances `next_run_date` to the next occurrence, and shows a flash message listing what was added.

## Depends on

- Step 07 (add expense) — must be implemented, as templates share the same form-building logic and validation
- Step 03 (login/logout) — must be implemented, as recurring expense processing runs on login

## Routes

| Method | Path | Description | Access |
|--------|------|-------------|--------|
| `GET` / `POST` | `/templates` | List user's templates; delete selected template | logged-in |
| `GET` / `POST` | `/templates/add` | Save form data as a named reusable template | logged-in |
| `POST` | `/templates/{id}/delete` | Delete one template | logged-in |
| `GET` / `POST` | `/recurring/add` | Create a recurring schedule from a template | logged-in |
| `GET` | `/recurring` | List user's recurring schedules | logged-in |
| `POST` | `/recurring/{id}/delete` | Delete one recurring schedule | logged-in |
| `POST` | `/recurring/{id}/run-now` | Trigger one occurrence immediately | logged-in |

## Database changes

### New tables

```sql
CREATE TABLE expense_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    name        TEXT    NOT NULL,          -- display name chosen by user
    amount      REAL    NOT NULL,
    category    TEXT    NOT NULL,
    description TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE recurring_expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    template_id     INTEGER NOT NULL REFERENCES expense_templates(id),
    frequency       TEXT    NOT NULL,      -- 'daily' | 'weekly' | 'monthly'
    next_run_date   TEXT    NOT NULL,       -- YYYY-MM-DD, date of next occurrence
    description     TEXT,                  -- override template description (optional)
    is_active       INTEGER NOT NULL DEFAULT 1,  -- 1 = active, 0 = paused
    created_at      TEXT    DEFAULT (datetime('now'))
);
```

### Changes to init_db()

Add both `CREATE TABLE IF NOT EXISTS` statements inside the existing `init_db()` `executescript` block.

No existing schema changes required.

## Templates

- **Create:** `templates/templates.html` — lists all templates with delete buttons
- **Create:** `templates/add_template.html` — name + pre-filled amount / category / description from the add-expense form
- **Create:** `templates/recurring.html` — lists recurring schedules with status, next run date, and action buttons
- **Create:** `templates/add_recurring.html` — picks template + frequency + start date
- **Modify:** `templates/add_expense.html` — add "Save as template" checkbox below the form, plus a "Use template" dropdown at the top that pre-fills the form when selected

## Files to change

- `app.py` — add new routes above `if __name__ == '__main__'`
- `database/db.py` — add `init_db()` table definitions; add helper functions for templates and recurring
- `database/queries.py` — add query helpers for the two new tables
- `templates/add_expense.html` — template picker + save-as-template checkbox
- `static/css/style.css` — any new styles for the template/recur UIs

## Files to create

- `templates/templates.html`
- `templates/add_template.html`
- `templates/recurring.html`
- `templates/add_recurring.html`

## New dependencies

No new pip packages. All SQLite stdlib; all JS vanilla.

## Rules for implementation

- No SQLAlchemy or any ORM — raw `?`-parameterised SQL only
- No new pip packages — work within `requirements.txt` as-is
- Passwords hashed with werkzeug (existing pattern, unchanged)
- All templates extend `base.html`; use `url_for()` for every internal link — never hardcode a URL
- Use CSS variables from the existing stylesheet — never hardcode hex values in templates or inline styles
- Recurring expense processing hooks into the `login` route — run it via a call to a new `process_recurring_expenses(uid)` helper after `session["user_id"]` is set, before the redirect
- When a recurring expense fires, create a real expense row via `create_expense()`; update `next_run_date` using `dateutil` or hand-rolled date arithmetic (stdlib `datetime` + `relativedelta` from dateutil if available in requirements, otherwise plain `datetime` arithmetic)
- `app.py` runs on **port 5001** — do not change this
- Frequency advance logic:
  - `daily` → `next_run_date + 1 day`
  - `weekly` → `next_run_date + 7 days`
  - `monthly` → same day next month (use `calendar.monthrange` to handle month-ends safely)
- Template names are user-provided, free-text, max **40 characters**, stored as-is (no special rendering needed)

## Definition of done

- [ ] `expense_templates` and `recurring_expenses` tables exist and init on first run
- [ ] User can save a template from the Add Expense page ("Save as template" checkbox)
- [ ] User can select a template on the Add Expense page and the form pre-fills (amount, category, description)
- [ ] User can list, view, and delete templates at `/templates`
- [ ] User can create a recurring schedule at `/recurring/add` (picks template, frequency, start date)
- [ ] User can list and delete recurring schedules at `/recurring`
- [ ] User can trigger a recurring expense immediately at `/recurring/<id>/run-now`
- [ ] On login, due recurring expenses are silently created as real expense rows and `next_run_date` advances
- [ ] Flash message after login lists any recurring expenses that were auto-created
- [ ] All forms use the same validation patterns as the rest of the app