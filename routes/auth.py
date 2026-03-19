"""
Modulo autenticazione — Login / Logout.
Credenziali caricate da variabili d'ambiente.
"""

import os
import functools
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    """Decoratore: reindirizza al login se l'utente non è autenticato."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("autenticato"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Pagina di login."""
    if session.get("autenticato"):
        return redirect(url_for("valutazione.index"))

    errore = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        username_corretto = os.environ.get("LOGIN_USERNAME", "admin")
        password_corretta = os.environ.get("LOGIN_PASSWORD", "")

        if username == username_corretto and password == password_corretta:
            session["autenticato"] = True
            session["username"] = username
            next_url = request.args.get("next") or url_for("valutazione.index")
            return redirect(next_url)
        else:
            errore = "Credenziali non valide. Riprova."

    return render_template("login.html", errore=errore)


@auth_bp.route("/logout")
def logout():
    """Esegue il logout cancellando la sessione."""
    session.clear()
    return redirect(url_for("auth.login"))
