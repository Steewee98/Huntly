"""
Modulo 2 — Inserimento Manuale Candidati.
Form per aggiungere candidati al database.
"""

import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from database import get_db
from dedup import is_duplicate
from routes.auth import get_org_id
from datetime import datetime

# Blueprint per il modulo inserimento candidati
candidati_bp = Blueprint("candidati", __name__)


@candidati_bp.route("/candidati/get-calendly-info")
def get_calendly_info():
    """Restituisce calendly_url dell'utente corrente e email del candidato."""
    candidato_id = request.args.get("candidato_id")
    user_id = session.get("user_id")
    org_id = get_org_id()
    db = get_db()
    utente = db.execute("SELECT calendly_url FROM utenti WHERE id = ?", (user_id,)).fetchone()
    calendly_url = (utente["calendly_url"] if utente and utente["calendly_url"] else "") or ""
    email_candidato = ""
    nome_candidato = ""
    if candidato_id:
        c = db.execute(
            "SELECT nome, cognome, email FROM candidati WHERE id = ? AND organizzazione_id = ?",
            (candidato_id, org_id)
        ).fetchone()
        if c:
            email_candidato = c["email"] or ""
            nome_candidato = ((c["nome"] or "") + " " + (c["cognome"] or "")).strip()
    db.close()
    return jsonify({
        "calendly_url": calendly_url,
        "email_candidato": email_candidato,
        "nome_candidato": nome_candidato,
    })


@candidati_bp.route("/candidati/salva-email", methods=["POST"])
def salva_email():
    """Salva l'email di un candidato."""
    dati = request.get_json() or {}
    candidato_id = dati.get("candidato_id")
    email = (dati.get("email") or "").strip()
    if not candidato_id:
        return jsonify({"errore": "candidato_id mancante"}), 400
    org_id = get_org_id()
    db = get_db()
    db.execute(
        "UPDATE candidati SET email = ?, data_aggiornamento = CURRENT_TIMESTAMP WHERE id = ? AND organizzazione_id = ?",
        (email or None, candidato_id, org_id)
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@candidati_bp.route("/candidati")
def index():
    """Pagina del form di inserimento manuale."""
    return render_template("candidati.html")


@candidati_bp.route("/candidati/verifica_duplicato")
def verifica_duplicato():
    """
    Endpoint AJAX: controlla se un profilo è già presente nel database.
    GET /candidati/verifica_duplicato?nome=X&cognome=Y&azienda=Z&linkedin=URL
    """
    profilo = {
        "nome":     request.args.get("nome", "").strip(),
        "cognome":  request.args.get("cognome", "").strip(),
        "azienda":  request.args.get("azienda", "").strip(),
        "ruolo":    request.args.get("ruolo", "").strip(),
        "linkedin": request.args.get("linkedin", "").strip(),
    }
    db = get_db()
    dup, motivo, cand_id = is_duplicate(db, profilo)
    db.close()
    return jsonify({"duplicato": dup, "motivo": motivo, "candidato_id": cand_id})


@candidati_bp.route("/candidati/inserisci", methods=["POST"])
def inserisci():
    """Salva il nuovo candidato nel database e reindirizza alla valutazione."""
    nome = request.form.get("nome", "").strip()
    cognome = request.form.get("cognome", "").strip()
    ruolo_attuale = request.form.get("ruolo_attuale", "").strip()
    azienda = request.form.get("azienda", "").strip()
    anni_esperienza = request.form.get("anni_esperienza", 0)
    note = request.form.get("note", "").strip()
    tipo_profilo = request.form.get("tipo_profilo", "A")
    profilo_linkedin = request.form.get("profilo_linkedin", "").strip()

    if not nome or not cognome:
        flash("Nome e cognome sono obbligatori.", "errore")
        return redirect(url_for("candidati.index"))

    # Gestore di default in base al profilo
    gestore_default = "Admin" if tipo_profilo == "A" else ("Recruiter" if tipo_profilo == "B" else "Non assegnato")

    # Snapshot dei parametri usati per questa inserzione manuale
    parametri_str = json.dumps({
        'nome': nome,
        'cognome': cognome,
        'ruolo_attuale': ruolo_attuale,
        'azienda': azienda,
        'tipo_profilo': tipo_profilo,
    }, ensure_ascii=False)

    db = get_db()

    org_id = get_org_id()

    # Registra la ricerca manuale nella cronologia
    ricerca_cur = db.execute(
        """INSERT INTO ricerche_automatiche
           (tipo_profilo, parametri, profili_trovati, profili_importati, fonte, stato, organizzazione_id)
           VALUES (?, ?, 1, 1, 'manuale', 'completata', ?)""",
        (tipo_profilo, parametri_str, org_id)
    )
    ricerca_id = ricerca_cur.lastrowid

    cur = db.execute(
        """INSERT INTO candidati
           (nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo, ricerca_id, gestore, profilo_linkedin, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo, ricerca_id, gestore_default, profilo_linkedin or None, org_id),
    )
    db.commit()
    nuovo_id = cur.lastrowid
    db.close()

    # Passa automaticamente al modulo valutazione con i dati del candidato
    return redirect(url_for("valutazione.index", candidato_id=nuovo_id))


@candidati_bp.route("/candidati/da_cronologia", methods=["POST"])
def da_cronologia():
    """
    Salva un candidato partendo da una valutazione in cronologia.
    Restituisce JSON — usato via AJAX dalla pagina valutazione.
    """
    dati = request.get_json()
    nome = dati.get("nome", "").strip()
    cognome = dati.get("cognome", "").strip()
    ruolo_attuale = dati.get("ruolo_attuale", "").strip()
    azienda = dati.get("azienda", "").strip()
    anni_esperienza = dati.get("anni_esperienza") or 0
    note = dati.get("note", "").strip()
    tipo_profilo = dati.get("tipo_profilo", "A")
    valutazione_id = dati.get("valutazione_id")

    if not nome or not cognome:
        return jsonify({"errore": "Nome e cognome sono obbligatori"}), 400

    # Gestore di default in base al profilo
    gestore_default = "Admin" if tipo_profilo == "A" else ("Recruiter" if tipo_profilo == "B" else "Non assegnato")

    db = get_db()

    # Deduplicazione prima di creare il candidato
    dup, motivo_dup, cand_id_esistente = is_duplicate(db, {
        "nome": nome, "cognome": cognome,
        "azienda": azienda, "ruolo": ruolo_attuale,
    })
    if dup:
        db.close()
        return jsonify({
            "duplicato": True,
            "motivo": motivo_dup,
            "candidato_id": cand_id_esistente,
        }), 409

    # Recupera i dati della valutazione per copiarli sul candidato
    val = None
    if valutazione_id:
        val = db.execute(
            "SELECT * FROM valutazioni WHERE id = ?", (valutazione_id,)
        ).fetchone()

    org_id = get_org_id()
    cur = db.execute(
        """INSERT INTO candidati
           (nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo,
            punteggio, analisi, spunti, messaggio_outreach, gestore, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo,
            val["punteggio"] if val else None,
            val["analisi"] if val else None,
            val["spunti"] if val else None,
            val["messaggio_outreach"] if val else None,
            gestore_default,
            org_id,
        ),
    )
    db.commit()
    nuovo_id = cur.lastrowid
    db.close()

    return jsonify({"successo": True, "candidato_id": nuovo_id})
