import calendar
import sqlite3
from datetime import date, datetime

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    advance_recurring,
    create_expense,
    create_recurring,
    create_template,
    create_user,
    delete_recurring,
    delete_template,
    get_db,
    get_recurring_by_id,
    get_template_by_id,
    get_user_by_email,
    get_user_by_email_for_update,
    get_user_row_by_id,
    init_db,
    seed_db,
    toggle_recurring,
    update_recurring_next_date,
    update_user_password,
    update_user_profile,
)
from database.queries import (
    delete_all_expenses_for_user,
    delete_expense_record,
    get_category_breakdown,
    get_expense_by_id,
    get_recurring_schedules,
    get_recent_transactions,
    get_summary_stats,
    get_templates,
    get_user_by_id,
    process_recurring_expenses,
    update_expense,
)

app = Flask(__name__)
app.secret_key = "dev-secret-key"

with app.app_context():
    init_db()
    seed_db()


def _parse_date(val):
    try:
        datetime.strptime(val, "%Y-%m-%d")
        return val
    except (ValueError, TypeError):
        return None


def _months_ago(today, n):
    m, y = today.month - n, today.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, email, password, confirm_password]):
            flash("All fields are required.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        try:
            create_user(name, email, password)
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
            return render_template("register.html")

        flash("Account created! Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]

        added = process_recurring_expenses(user["id"])
        if added:
            flash(f"Auto-logged recurring expense(s): {', '.join(added)}", "success")

        return redirect(url_for("profile"))

    return render_template("login.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    today = date.today()

    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))
    search = request.args.get("q", "").strip() or None

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = date_to = None

    today_str = today.isoformat()
    this_month_from = today.replace(day=1).isoformat()
    this_month_to = today.replace(
        day=calendar.monthrange(today.year, today.month)[1]
    ).isoformat()

    presets = {
        "this_month": {"date_from": this_month_from, "date_to": this_month_to},
        "last_3":     {"date_from": _months_ago(today, 3), "date_to": today_str},
        "last_6":     {"date_from": _months_ago(today, 6), "date_to": today_str},
    }

    return render_template(
        "profile.html",
        user=get_user_by_id(uid),
        stats=get_summary_stats(uid, date_from, date_to, search=search),
        expenses=get_recent_transactions(uid, date_from=date_from, date_to=date_to, search=search),
        categories=get_category_breakdown(uid, date_from, date_to, search=search),
        date_from=date_from,
        date_to=date_to,
        presets=presets,
        search=search,
    )


# ------------------------------------------------------------------ #
# Edit Profile — Step 12                                              #
# ------------------------------------------------------------------ #

MIN_PASSWORD_LEN = 6


@app.route("/profile/edit", methods=["GET", "POST"])
def edit_profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    user_row = get_user_row_by_id(uid)
    if user_row is None:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        cur_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        conf_pw = request.form.get("confirm_password", "")
        want_password_change = bool(new_pw)

        errors = []

        # Re-authenticate first — current password is required for any change
        if not check_password_hash(user_row["password_hash"], cur_pw):
            errors.append("Current password is incorrect.")

        # Name
        if not name:
            errors.append("Name is required.")
        elif len(name) > 80:
            errors.append("Name must be 80 characters or fewer.")

        # Email
        if not email or "@" not in email or "." not in email:
            errors.append("Please enter a valid email address.")
        else:
            collide = get_user_by_email_for_update(email, uid)
            if collide is not None:
                errors.append("Email already registered.")

        # Password change — only validated when user opted in
        if want_password_change:
            if new_pw != conf_pw:
                errors.append("New passwords do not match.")
            elif len(new_pw) < MIN_PASSWORD_LEN:
                errors.append(
                    f"New password must be at least {MIN_PASSWORD_LEN} characters."
                )

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "edit_profile.html",
                form={"name": name, "email": email},
                want_password_change=want_password_change,
            )

        try:
            update_user_profile(uid, name, email)
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
            return render_template(
                "edit_profile.html",
                form={"name": name, "email": email},
                want_password_change=want_password_change,
            )

        if want_password_change:
            update_user_password(uid, new_pw)

        # Keep navbar greeting in sync with the new name
        session["user_name"] = name
        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    # GET — render with current DB values
    return render_template(
        "edit_profile.html",
        form={"name": user_row["name"], "email": user_row["email"]},
        want_password_change=False,
    )


VALID_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_val = request.form.get("date", "").strip()
        description = request.form.get("description", "").strip()

        errors = []

        # amount: required, must be positive number
        try:
            amount = float(amount_raw)
            if amount <= 0:
                errors.append("Amount must be greater than zero.")
        except ValueError:
            errors.append("Please enter a valid amount.")

        # category: required, must be one of the 7
        if category not in VALID_CATEGORIES:
            errors.append("Please select a valid category.")

        # date: required, must be valid YYYY-MM-DD, not in future
        try:
            dt = datetime.strptime(date_val, "%Y-%m-%d")
            if dt.date() > date.today():
                errors.append("Date cannot be in the future.")
        except (ValueError, TypeError):
            errors.append("Please select a valid date.")

        # description: optional, store None if blank
        description = description if description else None

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "add_expense.html",
                values={
                    "amount": amount_raw,
                    "category": category,
                    "date": date_val,
                    "description": description or "",
                },
                templates=get_templates(session["user_id"]),
            )

        create_expense(session["user_id"], amount, category, date_val, description)

        # Handle "save as template" checkbox
        if request.form.get("save_template"):
            tmpl_name = request.form.get("template_name", "").strip()
            if tmpl_name and len(tmpl_name) <= 40:
                create_template(session["user_id"], tmpl_name, amount, category, description)

        flash("Expense added successfully.", "success")
        return redirect(url_for("profile"))

    # GET: check for template_id to pre-fill
    template_id = request.args.get("template_id", type=int)
    template_prefill = None
    if template_id:
        template_prefill = get_template_by_id(template_id, session["user_id"])

    default_values = {"date": date.today().isoformat()}
    if template_prefill:
        default_values["amount"] = str(template_prefill["amount"])
        default_values["category"] = template_prefill["category"]
        default_values["description"] = template_prefill["description"] or ""

    return render_template(
        "add_expense.html",
        values=default_values,
        templates=get_templates(session["user_id"]),
    )


# ------------------------------------------------------------------ #
# Templates                                                           #
# ------------------------------------------------------------------ #

@app.route("/templates", methods=["GET", "POST"])
def templates():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]

    if request.method == "POST":
        delete_id = request.form.get("delete_id", type=int)
        if delete_id:
            tmpl = get_template_by_id(delete_id, uid)
            if tmpl:
                delete_template(delete_id, uid)
                flash("Template deleted.", "success")

    all_templates = get_templates(uid)
    return render_template("templates.html", templates=all_templates)


@app.route("/templates/add", methods=["GET", "POST"])
def add_template():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        errors = []
        if not name or len(name) > 40:
            errors.append("Template name is required (max 40 characters).")
        try:
            amount = float(amount_raw)
            if amount <= 0:
                errors.append("Amount must be greater than zero.")
        except ValueError:
            errors.append("Please enter a valid amount.")
        if category not in VALID_CATEGORIES:
            errors.append("Please select a valid category.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "add_template.html",
                values={
                    "name": name,
                    "amount": amount_raw,
                    "category": category,
                    "description": description,
                },
            )

        create_template(uid, name, amount, category, description or None)
        flash("Template created.", "success")
        return redirect(url_for("templates"))

    # GET — pre-fill from query params if coming from add_expense save-as-template flow
    values = {
        "name": request.args.get("name", ""),
        "amount": request.args.get("amount", ""),
        "category": request.args.get("category", ""),
        "description": request.args.get("description", ""),
    }
    return render_template("add_template.html", values=values)


@app.route("/templates/<int:id>/use")
def use_template(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    tmpl = get_template_by_id(id, session["user_id"])
    if not tmpl:
        flash("Template not found.", "error")
        return redirect(url_for("templates"))
    return redirect(url_for("add_expense", template_id=id))


@app.route("/templates/<int:id>/delete", methods=["POST"])
def delete_template_route(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    tmpl = get_template_by_id(id, session["user_id"])
    if not tmpl:
        flash("Template not found.", "error")
        return redirect(url_for("templates"))
    delete_template(id, session["user_id"])
    flash("Template deleted.", "success")
    return redirect(url_for("templates"))


# ------------------------------------------------------------------ #
# Recurring expenses                                                  #
# ------------------------------------------------------------------ #

@app.route("/recurring", methods=["GET"])
def recurring():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    schedules = get_recurring_schedules(session["user_id"])
    return render_template("recurring.html", recurring=schedules)


@app.route("/recurring/add", methods=["GET", "POST"])
def add_recurring():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    all_templates = get_templates(uid)

    if request.method == "POST":
        template_id_raw = request.form.get("template_id", "").strip()
        frequency = request.form.get("frequency", "").strip()
        start_date = request.form.get("start_date", "").strip()
        description = request.form.get("description", "").strip()

        errors = []

        if template_id_raw:
            try:
                template_id = int(template_id_raw)
                tmpl = get_template_by_id(template_id, uid)
            except ValueError:
                tmpl = None
            if not tmpl:
                errors.append("Please select a valid template.")
        else:
            template_id = None
            errors.append("Please select a template.")

        valid_freqs = ["daily", "weekly", "monthly"]
        if frequency not in valid_freqs:
            errors.append("Please select a frequency.")

        try:
            dt = datetime.strptime(start_date, "%Y-%m-%d")
            if dt.date() > date.today():
                errors.append("Start date cannot be in the future.")
        except (ValueError, TypeError):
            errors.append("Please select a valid start date.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "add_recurring.html",
                values={
                    "template_id": template_id_raw,
                    "frequency": frequency,
                    "start_date": start_date,
                    "description": description,
                },
                templates=all_templates,
            )

        create_recurring(uid, template_id, frequency, start_date, description or None)
        flash("Recurring expense scheduled.", "success")
        return redirect(url_for("recurring"))

    # GET
    return render_template(
        "add_recurring.html",
        values={"start_date": date.today().isoformat()},
        templates=all_templates,
    )


@app.route("/recurring/<int:id>/run-now", methods=["POST"])
def run_recurring_now(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    item = get_recurring_by_id(id, uid)
    if not item:
        flash("Recurring expense not found.", "error")
        return redirect(url_for("recurring"))

    today = date.today().isoformat()
    desc = item["description"] if item["description"] else item["template_name"]
    create_expense(uid, item["amount"], item["category"], today, desc)

    advance_recurring(id, uid)

    flash(f"'{item['template_name']}' logged for today.", "success")
    return redirect(url_for("recurring"))


@app.route("/recurring/<int:id>/toggle", methods=["POST"])
def toggle_recurring_route(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    item = get_recurring_by_id(id, session["user_id"])
    if not item:
        flash("Recurring expense not found.", "error")
        return redirect(url_for("recurring"))

    toggle_recurring(id, session["user_id"])
    status = "paused" if item["is_active"] else "active"
    flash(f"Recurring expense is now {status}.", "success")
    return redirect(url_for("recurring"))


@app.route("/recurring/<int:id>/delete", methods=["POST"])
def delete_recurring_route(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    item = get_recurring_by_id(id, uid)
    if not item:
        flash("Recurring expense not found.", "error")
        return redirect(url_for("recurring"))

    delete_recurring(id, uid)
    flash("Recurring expense deleted.", "success")
    return redirect(url_for("recurring"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_val = request.form.get("date", "").strip()
        description = request.form.get("description", "").strip()

        errors = []
        try:
            amount = float(amount_raw)
            if amount <= 0:
                errors.append("Amount must be greater than zero.")
        except ValueError:
            errors.append("Please enter a valid amount.")
        if category not in VALID_CATEGORIES:
            errors.append("Please select a valid category.")
        try:
            dt = datetime.strptime(date_val, "%Y-%m-%d")
            if dt.date() > date.today():
                errors.append("Date cannot be in the future.")
        except (ValueError, TypeError):
            errors.append("Please select a valid date.")

        description = description if description else None

        if errors:
            for err in errors:
                flash(err, "error")
            expense = get_expense_by_id(id, uid)
            if expense is None:
                flash("Expense not found.", "error")
                return redirect(url_for("profile"))
            return render_template("edit_expense.html", expense=expense, categories=VALID_CATEGORIES)

        update_expense(id, uid, amount, category, date_val, description)
        flash("Expense updated successfully.", "success")
        return redirect(url_for("profile"))

    # GET
    expense = get_expense_by_id(id, uid)
    if expense is None:
        flash("Expense not found or access denied.", "error")
        return redirect(url_for("profile"))
    return render_template("edit_expense.html", expense=expense, categories=VALID_CATEGORIES)


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    expense = get_expense_by_id(id, uid)
    if expense is None:
        flash("Expense not found or access denied.", "error")
        return redirect(url_for("profile"))

    delete_expense_record(id, uid)
    flash("Expense deleted successfully.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/clear", methods=["POST"])
def clear_all_expenses():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method != "POST":
        abort(405)

    uid = session["user_id"]
    delete_all_expenses_for_user(uid)
    flash("All expenses cleared.", "success")
    return redirect(url_for("profile"))


if __name__ == '__main__':
    app.run(debug=True, port=8080)
