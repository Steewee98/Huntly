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


def _load_costi(db) -> dict:
    """Carica costi configurabili da config_costi."""
    rows = db.execute("SELECT chiave, valore FROM config_costi").fetchall()
    return {r["chiave"]: float(r["valore"]) for r in rows}


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
    tot_ricerche_mese = db.execute("SELECT COALESCE(SUM(ricerche), 0) AS n FROM utilizzo_mensile WHERE mese = ?", (mese,)).fetchone()["n"]
    tot_analisi_mese = db.execute("SELECT COALESCE(SUM(analisi_ai), 0) AS n FROM utilizzo_mensile WHERE mese = ?", (mese,)).fetchone()["n"]
    arricchimenti_mese = db.execute(
        "SELECT COUNT(*) AS n FROM candidati WHERE dati_proxycurl IS NOT NULL AND data_inserimento >= DATE_TRUNC('month', NOW())"
    ).fetchone()["n"]

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

    # --- Costi configurabili ---
    costi_cfg = _load_costi(db)

    # --- Previsioni ---
    nuovi_paganti_media = db.execute("""
        SELECT COUNT(*) / 3.0 AS n FROM organizzazioni
        WHERE piano IN ('pro', 'business')
        AND creato_il > NOW() - INTERVAL '3 months'
    """).fetchone()["n"] or 0

    db.close()

    # --- Calcoli contabilità ---
    costo_apify = round(tot_ricerche_mese * costi_cfg.get("costo_apify_per_ricerca", 0), 2)
    costo_anthropic = round(tot_analisi_mese * costi_cfg.get("costo_anthropic_per_analisi", 0), 2)
    costo_enrichlayer = round(arricchimenti_mese * costi_cfg.get("costo_enrichlayer_per_arricchimento", 0), 2)
    costo_railway = round(costi_cfg.get("costo_railway_mensile", 0), 2)
    costi_totali = round(costo_apify + costo_anthropic + costo_enrichlayer + costo_railway, 2)

    arr = mrr * 12
    margine = round(mrr - costi_totali, 2)
    margine_pct = round((margine / mrr * 100) if mrr > 0 else 0, 1)

    # Previsioni a 3, 6, 12 mesi
    paganti_attuali = max(org_pro + org_business, 1)
    previsioni = {}
    for m in (3, 6, 12):
        pro_prev = org_pro + (nuovi_paganti_media * m * 0.7)
        bus_prev = org_business + (nuovi_paganti_media * m * 0.3)
        mrr_prev = round((pro_prev * 49) + (bus_prev * 149))
        molt = (pro_prev + bus_prev) / paganti_attuali
        costi_prev = round(costi_totali * molt)
        previsioni[m] = {
            "mrr": mrr_prev,
            "costi": costi_prev,
            "margine": mrr_prev - costi_prev,
            "utenti_paganti": round(pro_prev + bus_prev),
        }

    return render_template(
        "admin.html",
        totale_org=totale_org,
        totale_utenti=totale_utenti,
        org_free=org_free,
        org_pro=org_pro,
        org_business=org_business,
        mrr=mrr,
        arr=arr,
        organizzazioni=organizzazioni,
        mese=mese,
        tot_ricerche_mese=tot_ricerche_mese,
        tot_analisi_mese=tot_analisi_mese,
        arricchimenti_mese=arricchimenti_mese,
        costi_cfg=costi_cfg,
        costo_apify=costo_apify,
        costo_anthropic=costo_anthropic,
        costo_enrichlayer=costo_enrichlayer,
        costo_railway=costo_railway,
        costi_totali=costi_totali,
        margine=margine,
        margine_pct=margine_pct,
        previsioni=previsioni,
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


# ─────────────────────────────────────────────
# POST /admin/salva-costi
# ─────────────────────────────────────────────

@admin_bp.route("/admin/salva-costi", methods=["POST"])
@admin_required
def salva_costi():
    dati = request.get_json() or {}
    chiavi_valide = (
        "costo_apify_per_ricerca",
        "costo_anthropic_per_analisi",
        "costo_enrichlayer_per_arricchimento",
        "costo_railway_mensile",
    )
    db = get_db()
    for chiave, valore in dati.items():
        if chiave not in chiavi_valide:
            continue
        db.execute(
            """INSERT INTO config_costi (chiave, valore, aggiornato_il)
               VALUES (?, ?, NOW())
               ON CONFLICT (chiave) DO UPDATE SET valore = ?, aggiornato_il = NOW()""",
            (chiave, valore, valore),
        )
    db.commit()
    db.close()
    log.info("[admin] Costi aggiornati: %s", dati)
    return jsonify({"ok": True})
