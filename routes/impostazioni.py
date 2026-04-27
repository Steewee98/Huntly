"""
Modulo Impostazioni — Account, piano, team e organizzazione.
"""

import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db
from routes.auth import get_org_id
from config import PIANI
import logging

log = logging.getLogger(__name__)

impostazioni_bp = Blueprint("impostazioni", __name__)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _get_utilizzo(db, org_id: int) -> dict:
    """Utilizzo mese corrente per l'organizzazione."""
    mese = datetime.now().strftime('%Y-%m')
    row = db.execute(
        "SELECT ricerche, analisi_ai FROM utilizzo_mensile WHERE organizzazione_id = ? AND mese = ?",
        (org_id, mese)
    ).fetchone()
    return {
        'ricerche':   row['ricerche']   if row else 0,
        'analisi_ai': row['analisi_ai'] if row else 0,
    }


def _get_conteggi(db, org_id: int) -> dict:
    """Conteggi reali candidati e profili target."""
    c = db.execute(
        "SELECT COUNT(*) AS n FROM candidati WHERE organizzazione_id = ?", (org_id,)
    ).fetchone()
    pt = db.execute(
        "SELECT COUNT(*) AS n FROM profili_target WHERE organizzazione_id = ? AND attivo = TRUE", (org_id,)
    ).fetchone()
    return {
        'candidati':      c['n']  if c  else 0,
        'profili_target': pt['n'] if pt else 0,
    }


def _piano_org(db, org_id: int) -> dict:
    """Legge piano dell'organizzazione e restituisce il dict PIANI corrispondente."""
    org = db.execute("SELECT piano FROM organizzazioni WHERE id = ?", (org_id,)).fetchone()
    chiave = (org['piano'] if org else 'free') or 'free'
    return PIANI.get(chiave, PIANI['free']), chiave


# ─────────────────────────────────────────────
# GET /impostazioni
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/salva-calendly", methods=["POST"])
def salva_calendly():
    user_id = session.get("user_id")
    dati = request.get_json() or {}
    url = (dati.get("calendly_url") or "").strip()
    db = get_db()
    db.execute("UPDATE utenti SET calendly_url = ? WHERE id = ?", (url or None, user_id))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@impostazioni_bp.route("/impostazioni")
def index():
    org_id   = get_org_id()
    user_id  = session.get("user_id")
    db       = get_db()

    # Utente corrente
    utente = db.execute("SELECT * FROM utenti WHERE id = ?", (user_id,)).fetchone() or {}

    # Organizzazione
    org = db.execute("SELECT * FROM organizzazioni WHERE id = ?", (org_id,)).fetchone() or {}

    # Piano
    piano_info, piano_chiave = _piano_org(db, org_id)

    # Utilizzo e conteggi
    utilizzo  = _get_utilizzo(db, org_id)
    conteggi  = _get_conteggi(db, org_id)

    # Membri team
    membri = db.execute(
        "SELECT id, nome, email, ruolo, creato_il FROM utenti WHERE organizzazione_id = ? AND attivo = TRUE ORDER BY creato_il",
        (org_id,)
    ).fetchall()

    # Inviti pendenti
    inviti = db.execute(
        "SELECT id, email, token, creato_il FROM inviti_team WHERE organizzazione_id = ? AND accettato = FALSE ORDER BY creato_il DESC",
        (org_id,)
    ).fetchall()

    db.close()

    return render_template(
        "impostazioni.html",
        utente=utente,
        org=org,
        piano_info=piano_info,
        piano_chiave=piano_chiave,
        utilizzo=utilizzo,
        conteggi=conteggi,
        membri=membri,
        inviti=inviti,
        piani=PIANI,
    )


# ─────────────────────────────────────────────
# POST /impostazioni/aggiorna-profilo
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/aggiorna-profilo", methods=["POST"])
def aggiorna_profilo():
    user_id = session.get("user_id")
    dati    = request.get_json() or {}
    nome    = (dati.get("nome") or "").strip()
    email   = (dati.get("email") or "").strip().lower()

    if not nome or not email or "@" not in email:
        return jsonify({"errore": "Nome e email validi sono obbligatori"}), 400

    db = get_db()
    # Controlla che l'email non sia già usata da un altro utente
    conflitto = db.execute(
        "SELECT id FROM utenti WHERE LOWER(email) = ? AND id <> ?", (email, user_id)
    ).fetchone()
    if conflitto:
        db.close()
        return jsonify({"errore": "Email già in uso da un altro account"}), 409

    db.execute(
        "UPDATE utenti SET nome = ?, email = ? WHERE id = ?", (nome, email, user_id)
    )
    db.commit()
    db.close()

    # Aggiorna sessione
    session["nome"]     = nome
    session["username"] = email
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# POST /impostazioni/cambia-password
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/cambia-password", methods=["POST"])
def cambia_password():
    user_id        = session.get("user_id")
    dati           = request.get_json() or {}
    password_attuale = (dati.get("password_attuale") or "").strip()
    nuova_password   = (dati.get("nuova_password") or "").strip()
    conferma         = (dati.get("conferma") or "").strip()

    if not password_attuale or not nuova_password:
        return jsonify({"errore": "Tutti i campi sono obbligatori"}), 400
    if nuova_password != conferma:
        return jsonify({"errore": "Le password non coincidono"}), 400
    if len(nuova_password) < 8:
        return jsonify({"errore": "La nuova password deve avere almeno 8 caratteri"}), 400

    db    = get_db()
    utente = db.execute("SELECT password_hash FROM utenti WHERE id = ?", (user_id,)).fetchone()
    if not utente or not check_password_hash(utente["password_hash"], password_attuale):
        db.close()
        return jsonify({"errore": "Password attuale non corretta"}), 401

    db.execute(
        "UPDATE utenti SET password_hash = ? WHERE id = ?",
        (generate_password_hash(nuova_password), user_id)
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# POST /impostazioni/aggiorna-organizzazione
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/aggiorna-organizzazione", methods=["POST"])
def aggiorna_organizzazione():
    org_id = get_org_id()
    dati   = request.get_json() or {}
    nome   = (dati.get("nome") or "").strip()

    if not nome:
        return jsonify({"errore": "Il nome organizzazione è obbligatorio"}), 400

    db = get_db()
    db.execute("UPDATE organizzazioni SET nome = ? WHERE id = ?", (nome, org_id))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# POST /impostazioni/invita-membro
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/invita-membro", methods=["POST"])
def invita_membro():
    org_id = get_org_id()
    dati   = request.get_json() or {}
    email  = (dati.get("email") or "").strip().lower()

    if not email or "@" not in email:
        return jsonify({"errore": "Email non valida"}), 400

    db = get_db()
    piano_info, _ = _piano_org(db, org_id)

    # Controlla limite utenti del piano
    n_membri = db.execute(
        "SELECT COUNT(*) AS n FROM utenti WHERE organizzazione_id = ? AND attivo = TRUE", (org_id,)
    ).fetchone()["n"] or 0
    n_inviti = db.execute(
        "SELECT COUNT(*) AS n FROM inviti_team WHERE organizzazione_id = ? AND accettato = FALSE", (org_id,)
    ).fetchone()["n"] or 0

    utenti_max = piano_info["utenti_max"]
    if utenti_max != -1 and (n_membri + n_inviti) >= utenti_max:
        db.close()
        return jsonify({"errore": f"Hai raggiunto il limite di {utenti_max} utenti del tuo piano. Upgrada per aggiungere altri membri."}), 403

    # Genera token
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO inviti_team (organizzazione_id, email, token) VALUES (?, ?, ?)",
        (org_id, email, token)
    )
    db.commit()
    db.close()

    return jsonify({"ok": True, "token": token, "email": email})


# ─────────────────────────────────────────────
# GET /impostazioni/accetta-invito/<token>
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/accetta-invito/<token>")
def accetta_invito(token):
    from flask import redirect, url_for
    db  = get_db()
    inv = db.execute(
        "SELECT * FROM inviti_team WHERE token = ? AND accettato = FALSE", (token,)
    ).fetchone()
    db.close()

    if not inv:
        from flask import flash
        flash("Link di invito non valido o già utilizzato.", "errore")
        return redirect(url_for("auth.login"))

    # Pre-compila la registrazione con email e token
    return redirect(url_for("auth.register") + f"?invite={token}&email={inv['email']}")


# ─────────────────────────────────────────────
# POST /impostazioni/rimuovi-membro/<user_id>
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/rimuovi-membro/<int:uid>", methods=["POST"])
def rimuovi_membro(uid):
    org_id  = get_org_id()
    user_id = session.get("user_id")

    if uid == user_id:
        return jsonify({"errore": "Non puoi rimuovere te stesso"}), 400

    db = get_db()
    # Verifica che il membro appartenga alla stessa org
    membro = db.execute(
        "SELECT id FROM utenti WHERE id = ? AND organizzazione_id = ?", (uid, org_id)
    ).fetchone()
    if not membro:
        db.close()
        return jsonify({"errore": "Membro non trovato"}), 404

    db.execute("UPDATE utenti SET attivo = FALSE WHERE id = ?", (uid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# POST /impostazioni/rimuovi-invito/<int:inv_id>
# ─────────────────────────────────────────────

@impostazioni_bp.route("/impostazioni/rimuovi-invito/<int:inv_id>", methods=["POST"])
def rimuovi_invito(inv_id):
    org_id = get_org_id()
    db = get_db()
    db.execute(
        "DELETE FROM inviti_team WHERE id = ? AND organizzazione_id = ?", (inv_id, org_id)
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})
