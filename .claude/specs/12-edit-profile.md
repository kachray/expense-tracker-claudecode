# Spec: Edit Profile

## Overview
Logged-in users currently see their name, email, and member-since info on `/profile`
but have no way to update that data after registration. This feature adds a
`/profile/edit` page where users can update their `name` (display name) and
`email` (with uniqueness validation), and optionally change their `password`
after confirming their current password. Updating name/email only requires the
current password as a soft re-authentication; changing the password additionally
requires a `new_password` + `confirm_password` pair. All edits target the same
`users` row that backs the existing profile page, so the updated values flow
through immediately on the next visit to `/profile`.

## Depends on
- Step 01: Database setup (`users` table, `get_db()`)
- Step 02: Registration (user rows exist; `users` schema with name/email/password_hash)
- Step 03: Login + Logout (`session["user_id"]` is set on successful login)
- Step 04: Profile Page (`profile.html` template exists — must show updated values)
- Step 05: Profile Page Backend Routes (`get_user_by_id` reused to re-fetch fresh data)

## Routes
- `GET  /profile/edit` — render the edit profile form pre-filled with current name and email — logged-in only (redirect to `/login` if no session, redirect to `/profile` after successful update)
- `POST /profile/edit` — process form, update DB, redirect to `/profile` with a flash — logged-in only

## Database changes
No schema changes. The `users` table already has `name`, `email`, `password_hash`, `created_at`.

Required `database/db.py` helpers to add:
- `get_user_by_email_for_update(email, exclude_user_id)` — look up a user by email excluding the user being edited (so a user can keep their own email). Returns the matching row or `None`.
- `update_user_profile(user_id, name, email)` — update `name` and `email` for the given user. Does NOT touch `password_hash`. Raises `sqlite3.IntegrityError` if the new email collides with another row.
- `update_user_password(user_id, new_password)` — hash `new_password` with `werkzeug.security.generate_password_hash` and write to `password_hash` for the given user.

> Note: the existing `get_user_by_id` helper in `database/queries.py` already
> returns the dict shape used by `profile.html` — no changes needed there.

## Templates
- **Create:** `templates/edit_profile.html`
  - Extends `base.html`
  - Renders a form with three fields:
    1. `name` (text, required, prefilled with current name)
    2. `email` (email, required, prefilled with current email)
    3. New password section (optional): `current_password` (required and visible if any of name/email/password fields are being changed), `new_password`, `confirm_password`
  - Shows flash messages (`error` / `success`) using `base.html` flash block
  - Displays a "Back to profile" link (`url_for('profile')`)
  - Pre-fills fields with previously-submitted values when validation fails (so users don't lose input)
  - Submit button labelled "Save Changes"

- **Modify:** `templates/profile.html`
  - Add an "Edit Profile" link/button in the user info card header that points to `url_for('edit_profile')`. Keep all existing visual design otherwise.

## Files to change
- `app.py` — add `edit_profile()` view handling `GET` and `POST`; import the new DB helpers from `database/db.py`
- `database/db.py` — add `get_user_by_email_for_update`, `update_user_profile`, `update_user_password`
- `templates/profile.html` — add an "Edit Profile" affordance in the user info card

## Files to create
- `templates/edit_profile.html`
- `static/css/edit_profile.css` — page-specific styles for the edit form (matching the existing `.profile-*` look-and-feel). Reuse the same CSS variable palette as `profile.css`.

## New dependencies
No new dependencies. Uses existing `werkzeug.security.generate_password_hash`, `check_password_hash`, and Flask's built-in `flash` / `redirect` / `url_for`.

## Rules for implementation
- No SQLAlchemy or ORMs — use raw `sqlite3` via `get_db()`
- Parameterised queries only — never use f-strings in SQL
- Passwords must always be hashed with `werkzeug.security.generate_password_hash` — never store plaintext
- All DB logic lives in `database/db.py`, never inline in route functions
- All templates extend `base.html`
- Use CSS variables — never hardcode hex values
- All internal links must use `url_for()` — no hardcoded URLs
- Authentication guard: check `session.get("user_id")`; if absent, `redirect(url_for("login"))`
- Re-authentication rule: every form submission MUST be re-verified by checking `current_password` against the user's stored `password_hash` using `check_password_hash`. If the current password is wrong, flash an error and re-render — do NOT persist any change.
- Email uniqueness: ignore the current user's own row when checking duplicates. Catch `sqlite3.IntegrityError` from `update_user_profile` as a safety net and flash a "Email already registered" error.
- Password change rule: only validate `new_password` / `confirm_password` if `new_password` is non-empty. If `new_password` is provided, `new_password == confirm_password` and minimum length 6 (reuse a clear constant).
- Name validation: must be non-empty after `.strip()`; max length 80 characters
- Email validation: must be non-empty after `.strip()`; must contain `@` and a `.`
- Preserve previously-submitted values on validation failure so users don't lose input
- On success: `flash("Profile updated successfully.", "success")` and `redirect(url_for("profile"))`
- Use `abort(405)` if an unsupported HTTP method reaches the route

## Definition of done
- [ ] `GET /profile/edit` while logged in returns HTTP 200 with the form pre-filled with current name/email
- [ ] `GET /profile/edit` while not logged in redirects to `/login`
- [ ] Submitting valid name + email + correct current password updates the user row and redirects to `/profile` with a success flash
- [ ] After update, visiting `/profile` shows the new name and email
- [ ] Submitting with the wrong `current_password` re-renders the form with an error and persists nothing
- [ ] Submitting with mismatched `new_password` / `confirm_password` re-renders the form with an error and persists nothing
- [ ] Submitting with a `new_password` of fewer than 6 characters re-renders with a clear error
- [ ] Submitting an empty `name` re-renders with a validation error
- [ ] Submitting a malformed email (no `@`) re-renders with a validation error
- [ ] Submitting an email already used by another user re-renders with "Email already registered"
- [ ] A user can keep their own email (no false duplicate error when re-submitting unchanged email)
- [ ] Passwords are stored as `werkzeug` hashes — never plaintext — verifiable by inspecting `spendly.db`
- [ ] The "Edit Profile" link on `/profile` uses `url_for('edit_profile')` — no hardcoded `href="/profile/edit"`
- [ ] No new pip packages were installed; `requirements.txt` unchanged
- [ ] No hex colour values appear in `edit_profile.html` — only CSS variables
