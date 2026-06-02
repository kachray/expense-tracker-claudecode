# Spec: Date Filter for Profile Page

## Overview
Add a date-range filter (start date + end date) to the `/profile` page so users can narrow down which expenses are shown and which time window the summary stats cover. The filter is passed as query parameters (`start_date`, `end_date`), applied server-side, and reflected in all three sections: summary stats, transaction table, and category breakdown.

## Depends on
- Step 4: Profile page UI (profile.html must exist and extend base.html)
- Step 5: Profile page backend routes (get_expenses_by_user, get_total_spent, get_expense_count, get_top_category, get_category_breakdown all exist in db.py)

## Routes
- `GET /profile` — accept optional `start_date` and `end_date` query params — logged-in only

## Database changes
No new tables or columns. The existing `expenses.date` TEXT column (ISO format `YYYY-MM-DD`) is used for filtering.

## Templates
- **Modify:** `templates/profile.html` — add a filter bar above the transaction table with:
  - A "From" `<input type="date">` bound to `start_date` query param
  - A "To" `<input type="date">` bound to `end_date` query param
  - A "Filter" submit button
  - A "Clear" button that resets to `/profile` (no date params)
  - Show current filter range as subtitle text when active

## Files to change
- `app.py` — modify the `/profile` view to read `start_date` / `end_date` from `request.args` and pass them to every stats and transactions helper
- `database/db.py` — add optional `start_date` and `end_date` parameters to: `get_expenses_by_user`, `get_total_spent`, `get_expense_count`, `get_top_category`, `get_category_breakdown`. When provided, each query adds `AND date >= ? AND date <= ?` to filter by range.

## Files to create
- None

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw sqlite3 with `?` placeholders
- Dates are ISO format (`YYYY-MM-DD`) strings passed as query params
- Handle missing or invalid dates gracefully: treat as "no filter" for that boundary
- All templates extend `base.html`
- Stats that have no matching expenses in the selected range must show `0` (not blank or error)
- The profile route continues to require authentication (redirect to `/login` if not logged in)
- Use `request.args.get()` for reading query params — do not use `request.form` for a GET filter