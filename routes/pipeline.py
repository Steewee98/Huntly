"""
Modulo 3 — Pipeline Candidati.
Tabella con tutti i candidati, stato avanzamento e azioni disponibili.
"""

import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from database import get_db
from ai_helpers import genera_messaggio_followup, rigenera_messaggio_followup

# Blueprint per il modulo pipeline
pipeline_bp = Blueprint("pipeline", __name__)

# Stati disponibili nel processo di selezione
STATI_VALIDI = ["Da contattare", "Contattato", "Risposto", "In valutazione", "Chiuso"]


@pipeline_bp.route("/pipeline")
def index():
    """Pagina principale della pipeline con tutti i candidati."""
    db = get_db()
    candidati = db.execute(
        "SELECT * FROM candidati ORDER BY data_aggiornamento DESC"
    ).fetchall()
    db.close()

    # Converti Row in dizionari per passarli al template
    candidati_lista = [dict(c) for c in candidati]

    # Deserializza gli spunti JSON per ogni candidato
    for c in candidati_lista:
        if c.get("spunti"):
            try:
                c["spunti"] = json.loads(c["spunti"])
            except Exception:
                c["spunti"] = []

    return render_template(
        "pipeline.html",
        candidati=candidati_lista,
        stati=STATI_VALIDI
    )


@pipeline_bp.route("/pipeline/aggiorna_stato", methods=["POST"])
def aggiorna_stato():
    """Endpoint AJAX per aggiornare lo stato di un candidato."""
    dati = request.get_json()
    candidato_id = dati.get("id")
    nuovo_stato = dati.get("stato")

    if nuovo_stato not in STATI_VALIDI:
        return jsonify({"errore": "Stato non valido"}), 400

    db = get_db()
    db.execute(
        "UPDATE candidati SET stato = ?, data_aggiornamento = CURRENT_TIMESTAMP WHERE id = ?",
        (nuovo_stato, candidato_id),
    )
    db.commit()
    db.close()

    return jsonify({"successo": True, "stato": nuovo_stato})


@pipeline_bp.route("/pipeline/followup/<int:candidato_id>", methods=["POST"])
def genera_followup(candidato_id):
    """Endpoint AJAX per generare un messaggio di follow-up con AI."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM candidati WHERE id = ?", (candidato_id,)
    ).fetchone()
    db.close()

    if not row:
        return jsonify({"errore": "Candidato non trovato"}), 404

    candidato = dict(row)
    messaggio = genera_messaggio_followup(candidato)
    return jsonify({"messaggio": messaggio})


@pipeline_bp.route("/pipeline/rigenera_followup/<int:candidato_id>", methods=["POST"])
def rigenera_followup(candidato_id):
    """Endpoint AJAX per rigenerare o riscrivere il follow-up con istruzioni personalizzate."""
    dati = request.get_json()
    messaggio_attuale = dati.get("messaggio_attuale", "").strip()
    istruzioni = dati.get("istruzioni", "").strip()

    db = get_db()
    row = db.execute("SELECT * FROM candidati WHERE id = ?", (candidato_id,)).fetchone()
    db.close()

    if not row:
        return jsonify({"errore": "Candidato non trovato"}), 404

    messaggio = rigenera_messaggio_followup(dict(row), messaggio_attuale, istruzioni)
    return jsonify({"messaggio": messaggio})


@pipeline_bp.route("/pipeline/elimina/<int:candidato_id>", methods=["DELETE"])
def elimina_candidato(candidato_id):
    """Elimina un candidato dalla pipeline."""
    db = get_db()
    db.execute("DELETE FROM candidati WHERE id = ?", (candidato_id,))
    db.commit()
    db.close()
    return jsonify({"successo": True})
