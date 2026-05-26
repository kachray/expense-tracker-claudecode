import sqlite3

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    get_category_breakdown,
    get_db,
    get_expense_count,
    get_expenses_by_user,
    get_total_spent,
    get_top_category,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)

app = Flask(__name__)
app.secret_key = "dev-secret-key"

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))
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
        return redirect(url_for("landing"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        flash("Welcome back!", "success")
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
        flash("Please sign in to view your profile.", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    db_user = get_user_by_id(user_id)

    name_parts = db_user["name"].split()
    initials = "".join(part[0] for part in name_parts[:2]).upper()
    member_since = db_user["created_at"][:7]  # "YYYY-MM"

    user = {
        "name": db_user["name"],
        "email": db_user["email"],
        "member_since": member_since,
        "initials": initials,
    }

    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None

    stats = {
        "total_spent": get_total_spent(user_id, start_date, end_date),
        "transaction_count": get_expense_count(user_id, start_date, end_date),
        "top_category": get_top_category(user_id, start_date, end_date),
    }

    transactions = get_expenses_by_user(user_id, start_date, end_date)
    categories = get_category_breakdown(user_id, start_date, end_date)

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        request=request,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)