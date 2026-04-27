"""
Modulo Admin — Dashboard amministrativa per monitorare organizzazioni,
utenti, utilizzo API e costi stimati. Accessibile solo a utenti con is_admin=TRUE.
"""

import csv
import io
import logging
from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session, redirect, Response
from database import get_db

log = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)

# ─────────────────────────────────────────────
# Decorator accesso admin
# ─────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect("/login")
        db = get_db()
        u = db.execute("SELECT is_admin FROM utenti WHERE id = ?", (user_id,)).fetchone()
        db.close()
        if not u or not u["is_admin"]:
            return "Accesso negato", 403
        log.info("[admin] Accesso admin da user_id=%s path=%s", user_id, request.path)
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# Costi stimati per unita
# ─────────────────────────────────────────────

COSTO_RICERCA = 0.50      # Apify run
COSTO_ANALISI = 0.03      # Claude API call
COSTO_ARRICCHIMENTO = 0.01  # EnrichLayer/Proxycurl


# ─────────────────────────────────────────────
# GET /admin — dashboard principale
# ─────────────────────────────────────────────

@admin_bp.route("/admin")
@admin_required
def index():
    db = get_db()
    mese = datetime.now().strftime("%Y-%m")

    # --- Panoramica ---
    totale_org = db.execute("SELECT COUNT(*) AS n FROM organizzazioni").fetchone()["n"]
    totale_utenti = db.execute("SELECT COUNT(*) AS n FROM utenti WHERE attivo = TRUE").fetchone()["n"]
    org_free = db.execute("SELECT COUNT(*) AS n FROM organizzazioni WHERE piano = 'free'").fetchone()["n"]
    org_pro = db.execute("SELECT COUNT(*) AS n FROM organizzazioni WHERE piano = 'pro'").fetchone()["n"]
    org_business = db.execute("SELECT COUNT(*) AS n FROM organizzazioni WHERE piano = 'business'").fetchone()["n"]
    mrr = (org_pro * 49) + (org_business * 149)

    # --- Lista organizzazioni con conteggi ---
    organizzazioni = db.execute("""
        SELECT o.id, o.nome, o.piano, o.creato_il,
            (SELECT COUNT(*) FROM utenti u WHERE u.organizzazione_id = o.id AND u.attivo = TRUE) AS n_utenti,
            (SELECT COUNT(*) FROM candidati c WHERE c.organizzazione_id = o.id) AS n_candidati,
            COALESCE((SELECT SUM(um.ricerche) FROM utilizzo_mensile um WHERE um.organizzazione_id = o.id), 0) AS tot_ricerche,
            COALESCE((SELECT SUM(um.analisi_ai) FROM utilizzo_mensile um WHERE um.organizzazione_id = o.id), 0) AS tot_analisi
        FROM organizzazioni o
        ORDER BY o.creato_il DESC
    """).fetchall()

    # --- Utilizzo API mese corrente ---
    row_ric = db.execute("SELECT COALESCE(SUM(ricerche), 0) AS n FROM utilizzo_mensile WHERE mese = ?", (mese,)).fetchone()
    row_ana = db.execute("SELECT COALESCE(SUM(analisi_ai), 0) AS n FROM utilizzo_mensile WHERE mese = ?", (mese,)).fetchone()
    tot_ricerche_mese = row_ric["n"]
    tot_analisi_mese = row_ana["n"]

    # --- Utenti recenti ---
    utenti_recenti = db.execute("""
        SELECT u.id, u.nome, u.email, u.ruolo, u.is_admin, u.creato_il,
               o.nome AS org_nome, o.piano AS org_piano
        FROM utenti u
        LEFT JOIN organizzazioni o ON o.id = u.organizzazione_id
        WHERE u.attivo = TRUE
        ORDER BY u.creato_il DESC LIMIT 20
    """).fetchall()

    # --- Attivita recente (con nome profilo target) ---
    attivita = db.execute("""
        SELECT o.nome AS org_nome,
               COALESCE(pt.nome, r.tipo_profilo) AS tipo,
               r.fonte, r.profili_trovati, r.data_ricerca
        FROM ricerche_automatiche r
        LEFT JOIN organizzazioni o ON o.id = r.organizzazione_id
        LEFT JOIN profili_target pt ON r.tipo_profilo = 'pt_' || pt.id::text
        ORDER BY r.data_ricerca DESC LIMIT 20
    """).fetchall()

    # --- Utenti per piano ---
    utenti_free = db.execute("""
        SELECT u.nome, u.email, u.creato_il, o.nome AS org_nome
        FROM utenti u
        JOIN organizzazioni o ON o.id = u.organizzazione_id
        WHERE o.piano = 'free' AND u.attivo = TRUE
        ORDER BY u.creato_il DESC
    """).fetchall()
    utenti_paganti = db.execute("""
        SELECT u.nome, u.email, u.creato_il, o.nome AS org_nome, o.piano
        FROM utenti u
        JOIN organizzazioni o ON o.id = u.organizzazione_id
        WHERE o.piano IN ('pro', 'business') AND u.attivo = TRUE
        ORDER BY u.creato_il DESC
    """).fetchall()

    db.close()

    costo_ricerche = round(tot_ricerche_mese * COSTO_RICERCA, 2)
    costo_analisi = round(tot_analisi_mese * COSTO_ANALISI, 2)
    costo_totale = round(costo_ricerche + costo_analisi, 2)

    return render_template(
        "admin.html",
        totale_org=totale_org,
        totale_utenti=totale_utenti,
        org_free=org_free,
        org_pro=org_pro,
        org_business=org_business,
        mrr=mrr,
        organizzazioni=organizzazioni,
        mese=mese,
        tot_ricerche_mese=tot_ricerche_mese,
        tot_analisi_mese=tot_analisi_mese,
        costo_ricerche=costo_ricerche,
        costo_analisi=costo_analisi,
        costo_totale=costo_totale,
        utenti_recenti=utenti_recenti,
        attivita=attivita,
        utenti_free=utenti_free,
        utenti_paganti=utenti_paganti,
    )


# ─────────────────────────────────────────────
# POST /admin/cambia-piano
# ─────────────────────────────────────────────

@admin_bp.route("/admin/cambia-piano", methods=["POST"])
@admin_required
def cambia_piano():
    dati = request.get_json() or {}
    org_id = dati.get("org_id")
    piano = dati.get("piano", "").strip()
    if not org_id or piano not in ("free", "pro", "business"):
        return jsonify({"errore": "Parametri non validi"}), 400
    db = get_db()
    db.execute("UPDATE organizzazioni SET piano = ? WHERE id = ?", (piano, org_id))
    db.commit()
    db.close()
    log.info("[admin] Piano org_id=%s cambiato a '%s'", org_id, piano)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# POST /admin/cambia-piano-email
# ─────────────────────────────────────────────

@admin_bp.route("/admin/cambia-piano-email", methods=["POST"])
@admin_required
def cambia_piano_email():
    dati = request.get_json() or {}
    email = (dati.get("email") or "").strip().lower()
    piano = (dati.get("piano") or "").strip()
    if not email or piano not in ("free", "pro", "business"):
        return jsonify({"errore": "Email e piano validi sono obbligatori"}), 400
    db = get_db()
    utente = db.execute("SELECT organizzazione_id FROM utenti WHERE LOWER(email) = ?", (email,)).fetchone()
    if not utente:
        db.close()
        return jsonify({"errore": "Utente non trovato"}), 404
    db.execute("UPDATE organizzazioni SET piano = ? WHERE id = ?", (piano, utente["organizzazione_id"]))
    db.commit()
    db.close()
    log.info("[admin] Piano cambiato a '%s' per org dell'utente %s", piano, email)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# POST /admin/imposta-admin
# ─────────────────────────────────────────────

@admin_bp.route("/admin/imposta-admin", methods=["POST"])
@admin_required
def imposta_admin():
    dati = request.get_json() or {}
    email = (dati.get("email") or "").strip().lower()
    is_admin = bool(dati.get("is_admin"))
    if not email:
        return jsonify({"errore": "Email obbligatoria"}), 400
    db = get_db()
    utente = db.execute("SELECT id FROM utenti WHERE LOWER(email) = ?", (email,)).fetchone()
    if not utente:
        db.close()
        return jsonify({"errore": "Utente non trovato"}), 404
    db.execute("UPDATE utenti SET is_admin = ? WHERE id = ?", (is_admin, utente["id"]))
    db.commit()
    db.close()
    log.info("[admin] is_admin=%s per utente %s", is_admin, email)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# GET /admin/esporta-csv
# ─────────────────────────────────────────────

@admin_bp.route("/admin/esporta-csv")
@admin_required
def esporta_csv():
    db = get_db()
    rows = db.execute("""
        SELECT o.nome AS organizzazione, o.piano, o.creato_il,
               COUNT(u.id) AS n_utenti
        FROM organizzazioni o
        LEFT JOIN utenti u ON u.organizzazione_id = o.id AND u.attivo = TRUE
        GROUP BY o.id, o.nome, o.piano, o.creato_il
        ORDER BY o.creato_il DESC
    """).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Organizzazione", "Piano", "Data Creazione", "N. Utenti"])
    for r in rows:
        writer.writerow([r["organizzazione"], r["piano"], r["creato_il"], r["n_utenti"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=huntly-org-{datetime.now().strftime('%Y%m%d')}.csv"},
    )
