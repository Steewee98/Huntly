"""
Modulo 2 — Inserimento Manuale Candidati.
Form per aggiungere candidati al database.
"""

import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import get_db
from datetime import datetime

# Blueprint per il modulo inserimento candidati
candidati_bp = Blueprint("candidati", __name__)


@candidati_bp.route("/candidati")
def index():
    """Pagina del form di inserimento manuale."""
    return render_template("candidati.html")


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

    if not nome or not cognome:
        flash("Nome e cognome sono obbligatori.", "errore")
        return redirect(url_for("candidati.index"))

    # Gestore di default in base al profilo
    gestore_default = "Salvatore Sabia" if tipo_profilo == "A" else ("Firdaous Filahi" if tipo_profilo == "B" else "Non assegnato")

    # Snapshot dei parametri usati per questa inserzione manuale
    parametri_str = json.dumps({
        'nome': nome,
        'cognome': cognome,
        'ruolo_attuale': ruolo_attuale,
        'azienda': azienda,
        'tipo_profilo': tipo_profilo,
    }, ensure_ascii=False)

    db = get_db()

    # Registra la ricerca manuale nella cronologia
    ricerca_cur = db.execute(
        """INSERT INTO ricerche_automatiche
           (tipo_profilo, parametri, profili_trovati, profili_importati, fonte, stato)
           VALUES (?, ?, 1, 1, 'manuale', 'completata')""",
        (tipo_profilo, parametri_str)
    )
    ricerca_id = ricerca_cur.lastrowid

    cur = db.execute(
        """INSERT INTO candidati
           (nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo, ricerca_id, gestore)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo, ricerca_id, gestore_default),
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
    gestore_default = "Salvatore Sabia" if tipo_profilo == "A" else ("Firdaous Filahi" if tipo_profilo == "B" else "Non assegnato")

    db = get_db()

    # Recupera i dati della valutazione per copiarli sul candidato
    val = None
    if valutazione_id:
        val = db.execute(
            "SELECT * FROM valutazioni WHERE id = ?", (valutazione_id,)
        ).fetchone()

    cur = db.execute(
        """INSERT INTO candidati
           (nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo,
            punteggio, analisi, spunti, messaggio_outreach, gestore)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            nome, cognome, ruolo_attuale, azienda, anni_esperienza, note, tipo_profilo,
            val["punteggio"] if val else None,
            val["analisi"] if val else None,
            val["spunti"] if val else None,
            val["messaggio_outreach"] if val else None,
            gestore_default,
        ),
    )
    db.commit()
    nuovo_id = cur.lastrowid
    db.close()

    return jsonify({"successo": True, "candidato_id": nuovo_id})
