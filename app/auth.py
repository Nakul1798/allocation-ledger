from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app import db
from app.forms import ChangePasswordForm, LoginForm, RegistrationForm
from app.models import Stakeholder

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = Stakeholder(
            full_name=form.full_name.data.strip(),
            email=form.email.data.strip().lower(),
            role=form.role.data,
            affiliated_university=(form.affiliated_university.data or "SRH").strip(),
            manual_status="ACTIVE",
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=False)
        flash(f"Welcome, {user.full_name.split()[0]}. Your account has been created.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = Stakeholder.query.filter_by(email=email).first()

        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash("This account is temporarily locked after repeated failed sign-ins. Try again later.", "error")
            return render_template("auth/login.html", form=form)

        # Deliberately identical error for "no such user" and "wrong password" so a
        # login attempt can't be used to discover which emails have accounts.
        if user is None or not user.check_password(form.password.data):
            if user is not None:
                user.failed_login_count += 1
                if user.failed_login_count >= current_app.config["MAX_LOGIN_ATTEMPTS"]:
                    user.locked_until = datetime.utcnow() + timedelta(
                        minutes=current_app.config["LOGIN_LOCKOUT_MINUTES"]
                    )
                    user.failed_login_count = 0
                db.session.commit()
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html", form=form)

        if user.manual_status == "IN ACTIVE":
            flash("This account has been deactivated. Contact your program director.", "error")
            return render_template("auth/login.html", form=form)

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        db.session.commit()

        login_user(user, remember=False)
        flash(f"Welcome back, {user.full_name.split()[0]}.", "success")
        next_url = request.args.get("next")
        if next_url and not next_url.startswith("/"):
            next_url = None
        return redirect(next_url or url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You've been signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Your current password is incorrect.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/change_password.html", form=form)
