# Spec: Profile Page Backend Routes

## Overview
Step 04 produced the profile page UI with hardcoded static data. Step 05 replaces that static data with real database queries — fetching the logged-in user's info, computing spending stats from the `expenses` table, loading recent transactions, and calculating category breakdowns. The UI layout and templates from Step 04 are reused unchanged.

## Depends on
- Step 1: Database setup (schema with users and expenses tables)
- Step 2: Registration (user accounts exist)
- Step 3: Login + Logout (session gives user_id)
- Step 4: Profile Page (profile.html template exists)

## Routes
- `GET /profile` — fetch real user data and stats from DB, render `profile.html` — logged-in only

## Database changes
No database changes. The existing `users` and `expenses` tables are sufficient.

Required `database/db.py` functions to add:
- `get_user_by_id(user_id)` — fetch a single user by their id
- `get_expenses_by_user(user_id)` — fetch all expenses for a user, ordered by date desc
- `get_total_spent(user_id)` — sum of all expense amounts for a user
- `get_expense_count(user_id)` — count of expenses for a user
- `get_top_category(user_id)` — category with highest total spend for a user
- `get_category_breakdown(user_id)` — per-category totals with percentages

## Templates
- No new templates. `profile.html` from Step 4 is reused.
- `app.py` passes the same context keys but populated from DB instead of hardcoded dicts:
  - `user` — `{name, email, member_since: YYYY-MM string, initials: first+last initial}`
  - `stats` — `{total_spent, transaction_count, top_category}`
  - `transactions` — list of `{date, description, category, amount}`
  - `categories` — list of `{name, amount, pct}`

## Files to change
- `database/db.py` — add the six functions listed above
- `app.py` — replace hardcoded profile data with calls to `database/db.py` functions

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use raw sqlite3 via `get_db()`
- Parameterised queries only — never f-string SQL
- Passwords hashed with werkzeug (handled in Step 2, no changes needed)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- All DB logic lives in `database/db.py`, not in route functions
- The `/expenses/add`, `/expenses/<id>/edit`, and `/expenses/<id>/delete` routes remain stubs — do not implement them in this step

## Definition of done
- [ ] `get_user_by_id(user_id)` returns correct user dict with name, email, created_at
- [ ] `get_expenses_by_user(user_id)` returns expenses ordered by date descending
- [ ] `get_total_spent(user_id)` returns a float sum correct to 2 decimal places
- [ ] `get_expense_count(user_id)` returns an integer count
- [ ] `get_top_category(user_id)` returns the category string with highest total spend
- [ ] `get_category_breakdown(user_id)` returns list with `name`, `amount`, `pct` keys; percentages sum to 100
- [ ] Visiting `/profile` while logged in shows real data from the database
- [ ] Visiting `/profile` without being logged in still redirects to `/login`
- [ ] Profile page UI (stats, transaction table, category breakdown) matches Step 4 layout