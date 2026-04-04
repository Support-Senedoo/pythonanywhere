from __future__ import annotations

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from web_app.dev_auth import try_dev_user
from web_app.users_store import verify_user

bp = Blueprint("public", __name__)


def login_required_client(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "client":
            flash("Connectez-vous via l’espace client.", "warning")
            return redirect(url_for("public.login", portal="client"))
        return view(*args, **kwargs)

    return wrapped


def login_required_staff(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "staff":
            flash("Connectez-vous via l’espace Senedoo.", "warning")
            return redirect(url_for("public.login", portal="staff"))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/")
def index():
    return render_template("home.html")


@bp.route("/health")
def health():
    return {"status": "ok"}, 200


@bp.route("/login", methods=["GET", "POST"])
def login():
    portal = (request.args.get("portal") or request.form.get("portal") or "client").lower()
    if portal not in ("client", "staff"):
        portal = "client"

    if request.method == "POST":
        login_name = (request.form.get("login") or "").strip()
        password = request.form.get("password") or ""

        from flask import current_app

        path = current_app.config["TOOLBOX_USERS_PATH"]
        user = try_dev_user(login_name, password, portal)
        if not user:
            user = verify_user(path, login_name, password)
        if not user:
            flash("Identifiant ou mot de passe incorrect.", "danger")
            return render_template("login.html", portal=portal), 401
        if portal == "client" and user.role != "client":
            flash("Ce compte n’est pas un accès client. Utilisez l’espace Senedoo.", "warning")
            return render_template("login.html", portal=portal), 403
        if portal == "staff" and user.role != "staff":
            flash("Ce compte n’est pas un accès équipe. Utilisez l’espace client.", "warning")
            return render_template("login.html", portal=portal), 403

        session.clear()
        session["logged_in"] = True
        session["login"] = user.login
        session["role"] = user.role
        session["client_id"] = user.client_id
        session["portal"] = portal
        if user.role == "staff":
            session.pop("staff_selected_client_id", None)

        if user.role == "client":
            return redirect(url_for("legacy.client_home"))
        return redirect(url_for("staff.staff_home"))

    return render_template("login.html", portal=portal)


@bp.route("/logout")
def logout():
    session.clear()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("public.index"))
