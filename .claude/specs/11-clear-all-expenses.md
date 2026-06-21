# Spec: Clear All Expenses

## Overview
A "Clear All Expenses" button is added to the profile page, allowing a logged-in user to permanently delete all of their own expense records in one action. This is a destructive operation and is implemented as a POST-only route with a confirmation step via a simple browser confirm dialog triggered by JavaScript.

## Depends on
- Steps 01–10 must be complete: database setup, registration, login/logout, profile page, add/edit/delete expense, and search.

## Routes
- `POST /expenses/clear` — deletes all expenses for the currently logged-in user — logged-in only

## Database changes
No new tables or columns. A new helper `delete_all_expenses_for_user(user_id)` is added to `database/queries.py` with a single `DELETE FROM expenses WHERE user_id = ?` statement.

## Templates
- **Modify:** `templates/profile.html` — add a "Clear All Expenses" button to the expense section, visible only to logged-in users.

## Files to change
- `app.py` — add the `POST /expenses/clear` route
- `database/queries.py` — add `delete_all_expenses_for_user(user_id)` helper
- `templates/profile.html` — add the clear-all button

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use raw SQLite with parameterized queries
- Route accepts only POST — GET requests return 405 Method Not Allowed
- The button triggers a JS `confirm()` dialog before submitting the form
- A flash message ("All expenses cleared.") is shown on success
- Only the logged-in user's own expenses are deleted (enforced via `user_id` in WHERE clause)
- All templates extend `base.html`
- Use CSS variables — no hardcoded hex values in any new or modified CSS

## Definition of done
1. A "Clear All Expenses" button is visible on the profile page for logged-in users.
2. Clicking the button triggers a browser confirm dialog ("Are you sure?" / "Cancel").
3. Confirming the dialog submits a POST to `/expenses/clear` and deletes all the user's expenses from the database.
4. After clearing, the user is redirected to `/profile` and sees a flash success message.
5. Refreshing `/profile` shows zero expenses listed.
6. Cancelling the confirm dialog submits nothing and the user stays on the profile page.
7. A GET request to `/expenses/clear` returns a 405 Method Not Allowed.
8. An unauthenticated request to `/expenses/clear` redirects to `/login`.
9. Each user's data is isolated — clearing expenses as one user does not affect another user's data.
10. No SQL is constructed with f-strings — all user identifiers are passed via `?` placeholders.