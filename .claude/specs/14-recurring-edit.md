# Spec: Edit Recurring Expense

## Overview

Add the ability to edit an existing recurring expense schedule. Users can change the template, frequency, start date, and optional description override without having to delete and recreate the entire schedule.

## Depends on

- Step 13 (expense templates and recurring) — must be implemented, as this feature edits an existing recurring expense schedule

## Routes

| Method | Path | Description | Access |
|--------|------|-------------|--------|
| `GET` / `POST` | `/recurring/<id>/edit` | Edit an existing recurring schedule | logged-in |

## Database changes

No new tables or columns. The existing `recurring_expenses` table has all required fields.

A new `update_recurring` helper is needed in `database/db.py` to update an existing recurring schedule's `template_id`, `frequency`, `next_run_date`, and `description`.

## Templates

- **Create:** `templates/edit_recurring.html` — same structure as `add_recurring.html` but pre-filled with the existing schedule values; submits to `POST /recurring/<id>/edit`

- **Modify:** `templates/recurring.html` — add an "Edit" button per recurring card, pointing to `{{ url_for('edit_recurring', id=r.id) }}`

## Files to change

- `app.py` — add `GET` / `POST` route `edit_recurring(id)`
- `database/db.py` — add `update_recurring(rec_id, user_id, template_id, frequency, next_run_date, description)` helper
- `templates/recurring.html` — add Edit button per recurring card

## Files to create

- `templates/edit_recurring.html`

## New dependencies

No new pip packages.

## Rules for implementation

- Same field validation as `add_recurring`: template_id must exist and belong to user, frequency must be one of `daily | weekly | monthly`, next_run_date must be a valid YYYY-MM-DD date
- Updating `next_run_date` does NOT auto-advance the schedule — it sets the date directly, giving the user full control (consistent with how `start_date` is set on create)
- No SQLAlchemy or any ORM — raw `?`-parameterised SQL only
- All templates extend `base.html`; use `url_for()` for every internal link
- Use CSS variables from the existing stylesheet — never hardcode hex values

## Definition of done

- [ ] "Edit" button appears on every recurring card on the `/recurring` page
- [ ] `GET /recurring/<id>/edit` renders the edit form pre-filled with current values
- [ ] `POST /recurring/<id>/edit` updates the schedule and redirects to `/recurring`
- [ ] If the schedule does not exist or belongs to another user, redirect to `/recurring` with an error flash
- [ ] Validation errors re-render the form with submitted values and error messages
- [ ] Template is consistent in style and layout with `add_recurring.html`