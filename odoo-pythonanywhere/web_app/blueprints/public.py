from __future__ import annotations

from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from web_app.dev_auth import dev_login_disabled, try_dev_user
from web_app.password_reset import consume_reset_token, issue_reset_token, send_reset_email
from web_app.users_store import get_user_row, set_user_password, verify_user

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
    portal = (request.args.get("portal") or request.form.get("portal") or "client").strip().lower()
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
            ln = login_name.strip().lower()
            pw = (password or "").strip()
            if ln == "test" and pw == "passer":
                if dev_login_disabled():
                    flash(
                        "La connexion automatique test/passer est désactivée "
                        "(TOOLBOX_DISABLE_DEV_LOGIN sur le serveur). "
                        "Utilisez un compte créé dans l’administration, ou un utilisateur « test » "
                        "dans toolbox_users.json dont le mot de passe correspond bien à « passer ».",
                        "danger",
                    )
                else:
                    flash(
                        "Connexion refusée avec test/passer. Vérifiez d’avoir choisi le bon portail "
                        "(client ou équipe) et rechargez la page ; en cas de doute, contactez l’administrateur.",
                        "danger",
                    )
            elif ln == "test":
                flash(
                    "Mot de passe incorrect pour l’identifiant « test ». "
                    "En démo, le mot de passe exact est « passer » (tout en minuscules, sans espace). "
                    "Sinon utilisez un compte défini dans l’administration.",
                    "danger",
                )
            else:
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
        session["client_id"] = (user.client_id or "").strip().lower() or None
        session["portal"] = portal
        if user.role == "staff":
            session.pop("staff_selected_client_id", None)

        if user.role == "client":
            return redirect(url_for("legacy.client_home"))
        return redirect(url_for("staff.staff_home"))

    return render_template("login.html", portal=portal)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        login = (request.form.get("login") or "").strip()
        path = current_app.config["TOOLBOX_USERS_PATH"]
        tok_path = current_app.config["TOOLBOX_PASSWORD_RESET_TOKENS_PATH"]
        row = get_user_row(path, login) if login else None
        if row:
            token = issue_reset_token(tok_path, row["login"])
            base = (current_app.config.get("TOOLBOX_PUBLIC_BASE_URL") or "").strip().rstrip("/")
            if not base:
                base = request.url_root.rstrip("/")
            reset_url = f"{base}{url_for('public.reset_password', token=token)}"
            host = current_app.config.get("TOOLBOX_SMTP_HOST") or ""
            mail_from = current_app.config.get("TOOLBOX_MAIL_FROM") or ""
            if not host or not mail_from:
                flash(
                    "L’envoi d’e-mails n’est pas configuré (SMTP). Contactez l’administrateur Senedoo.",
                    "danger",
                )
                return render_template("forgot_password.html"), 503
            try:
                send_reset_email(
                    to_addr=str(row["login"]),
                    reset_url=reset_url,
                    smtp_host=host,
                    smtp_port=int(current_app.config.get("TOOLBOX_SMTP_PORT") or 587),
                    smtp_user=current_app.config.get("TOOLBOX_SMTP_USER") or "",
                    smtp_password=current_app.config.get("TOOLBOX_SMTP_PASSWORD") or "",
                    mail_from=mail_from,
                )
                flash("Un e-mail avec un lien (valide 24 h) vous a été envoyé.", "success")
            except Exception as e:
                flash(f"Impossible d’envoyer l’e-mail : {e!s}", "danger")
                return render_template("forgot_password.html"), 500
        else:
            flash(
                "Si cet identifiant est enregistré, un e-mail de réinitialisation vient d’être envoyé.",
                "info",
            )
        return redirect(url_for("public.login"))
    return render_template("forgot_password.html")


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token = (request.args.get("token") or request.form.get("token") or "").strip()
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        pw2 = (request.form.get("password2") or "").strip()
        if pw != pw2:
            flash("Les deux mots de passe ne correspondent pas.", "danger")
            return render_template("reset_password.html", token=token), 400
        tok_path = current_app.config["TOOLBOX_PASSWORD_RESET_TOKENS_PATH"]
        users_path = current_app.config["TOOLBOX_USERS_PATH"]
        login = consume_reset_token(tok_path, token)
        if not login:
            flash("Lien invalide ou expiré. Demandez une nouvelle réinitialisation.", "danger")
            return redirect(url_for("public.forgot_password"))
        try:
            set_user_password(users_path, login, pw)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("reset_password.html", token=token), 400
        flash("Mot de passe mis à jour. Vous pouvez vous connecter.", "success")
        return redirect(url_for("public.login"))
    return render_template("reset_password.html", token=token)


@bp.route("/logout")
def logout():
    session.clear()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("public.index"))
