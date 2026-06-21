# Spec: Search Expenses

## Overview
Users can search their expense transactions by description text directly from the profile page. A search input field is added to the existing filter bar, allowing users to filter expenses by any text match in the description field while retaining the existing date range and preset filters.

## Depends on
- Steps 01–09 must be complete: database setup, registration, login/logout, profile page, add expense, edit expense, delete expense.

## Routes
No new routes. The search feature is integrated into the existing `GET /profile` route via query parameters.

## Database changes
No new tables or columns. An existing query in `database/queries.py` (`get_recent_transactions`) is extended with optional text search via SQL `LIKE`.

## Templates
- **Modify:** `templates/profile.html` — add a search text input to the filter bar form.

## Files to change
- `app.py` — read `q` query parameter and pass it through to the query helpers
- `database/queries.py` — extend `get_recent_transactions` (and related helpers that use it) to accept a `search` parameter and filter descriptions using `LIKE '%search%'`
- `templates/profile.html` — add search input field to the filter bar HTML

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use raw SQLite with parameterized queries
- `LIKE` pattern: `WHERE description LIKE '%' || ? || '%'` with the search term as a `?` parameter (never embed f-strings in SQL)
- Search is case-insensitive via SQLite's `LIKE` (which is already case-insensitive for ASCII)
- If no search term is provided, behave exactly as before — show all matching transactions within date range
- Preserve existing date filter behavior; search AND date filters work together
- All templates extend `base.html`
- Use CSS variables — no hardcoded hex values in any new or modified CSS

## Definition of done
1. Navigating to `/profile` without a search term renders the page exactly as before with all expenses visible (within date range).
2. Visiting `/profile?q=groceries` shows only expenses whose description contains "groceries" (case-insensitive).
3. Combining search and date filters works: `/profile?q=groceries&date_from=2026-06-01&date_to=2026-06-14` returns only matching expenses.
4. Preset filter links (All Time, This Month, etc.) do not break when a search term is active — they should preserve `q` when navigating.
5. Clearing the search input and re-submitting restores the full filtered list.
6. No hardcoded SQL values — all user input passed as parameterized query arguments.