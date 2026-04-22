"""
Modulo autenticazione — Login / Logout / Registrazione.
Autenticazione con email + password, multi-tenant per organizzazione.
"""

import functools
import re
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db

auth_bp = Blueprint("auth", __name__)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_org_id() -> int | None:
    """Restituisce l'organizzazione_id dalla sessione corrente."""
    org_id = session.get("organizzazione_id")
    if org_id is None and session.get("autenticato"):
        return 1   # fallback per sessioni legacy
    return org_id


def login_required(f):
    """Decoratore: reindirizza al login se l'utente non è autenticato."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("autenticato"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def _slug_from_name(nome: str) -> str:
    """Genera uno slug URL-safe dal nome organizzazione."""
    slug = nome.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:40] or "org"


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("autenticato"):
        return redirect(url_for("dashboard.index"))

    errore = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not email or not password:
            errore = "Email e password sono obbligatori."
        else:
            db = get_db()
            utente = db.execute(
                "SELECT * FROM utenti WHERE LOWER(email) = ? AND attivo = TRUE", (email,)
            ).fetchone()
            db.close()

            if utente and check_password_hash(utente["password_hash"], password):
                session.clear()
                session["autenticato"]      = True
                session["user_id"]          = utente["id"]
                session["organizzazione_id"] = utente["organizzazione_id"]
                session["username"]         = utente["email"]
                session["nome"]             = utente["nome"] or email.split("@")[0]
                next_url = request.args.get("next") or url_for("dashboard.index")
                return redirect(next_url)
            else:
                errore = "Email o password non validi."

    return render_template("login.html", errore=errore)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("autenticato"):
        return redirect(url_for("dashboard.index"))

    errore = None
    if request.method == "POST":
        nome_utente   = request.form.get("nome", "").strip()
        email         = request.form.get("email", "").strip().lower()
        password      = request.form.get("password", "").strip()
        password2     = request.form.get("password2", "").strip()
        nome_azienda  = request.form.get("nome_azienda", "").strip()

        # Validazioni
        if not all([nome_utente, email, password, nome_azienda]):
            errore = "Tutti i campi sono obbligatori."
        elif password != password2:
            errore = "Le password non coincidono."
        elif len(password) < 8:
            errore = "La password deve essere di almeno 8 caratteri."
        elif "@" not in email:
            errore = "Inserisci un indirizzo email valido."
        else:
            db = get_db()
            esistente = db.execute(
                "SELECT id FROM utenti WHERE LOWER(email) = ?", (email,)
            ).fetchone()

            if esistente:
                errore = "Esiste già un account con questa email."
                db.close()
            else:
                # Crea organizzazione
                slug_base = _slug_from_name(nome_azienda)
                slug = slug_base
                counter = 1
                while db.execute("SELECT id FROM organizzazioni WHERE slug = ?", (slug,)).fetchone():
                    slug = f"{slug_base}-{counter}"
                    counter += 1

                org_cur = db.execute(
                    "INSERT INTO organizzazioni (nome, slug, piano) VALUES (?, ?, 'free')",
                    (nome_azienda, slug)
                )
                org_id = org_cur.lastrowid

                # Crea utente admin
                pw_hash = generate_password_hash(password)
                db.execute(
                    """INSERT INTO utenti (organizzazione_id, email, password_hash, nome, ruolo)
                       VALUES (?, ?, ?, ?, 'admin')""",
                    (org_id, email, pw_hash, nome_utente)
                )
                db.commit()

                # Login automatico
                utente = db.execute(
                    "SELECT * FROM utenti WHERE LOWER(email) = ?", (email,)
                ).fetchone()
                db.close()

                session.clear()
                session["autenticato"]      = True
                session["user_id"]          = utente["id"]
                session["organizzazione_id"] = utente["organizzazione_id"]
                session["username"]         = utente["email"]
                session["nome"]             = utente["nome"] or email.split("@")[0]
                return redirect(url_for("dashboard.index"))

    return render_template("register.html", errore=errore)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
