"""
Modulo 3 — Pipeline Candidati.
Tabella con tutti i candidati, stato avanzamento e azioni disponibili.
Include i tab: Pipeline, Valutazione, Calendario, Cronologia.
"""

import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from database import get_db
from routes.auth import get_org_id
from ai_helpers import genera_messaggio_followup, rigenera_messaggio_followup

# Blueprint per il modulo pipeline
pipeline_bp = Blueprint("pipeline", __name__)

# Stati disponibili nel processo di selezione
STATI_VALIDI = ["Da valutare", "Da contattare", "Richiesta Inviata", "Messaggio Inviato", "Risposto", "In valutazione", "Chiuso"]

# Gestori disponibili
GESTORI_VALIDI = ["Admin", "Recruiter", "Non assegnato"]

# Costanti tab Calendario
TIPI_APPUNTAMENTO = ['Chiamata', 'Video call', 'Incontro di persona']
GESTORI_CAL = ['Admin', 'Recruiter']
STATI_APPUNTAMENTO = ['Da fare', 'Completato', 'Annullato']


@pipeline_bp.route("/pipeline")
def index():
    """Vista griglia — una card per ogni profilo target che ha candidati."""
    org_id = get_org_id()
    db = get_db()

    pipeline_per_profilo = db.execute("""
        SELECT
            pt.id,
            pt.nome,
            pt.colore,
            pt.scopo,
            COUNT(c.id)                                          AS totale_candidati,
            COUNT(CASE WHEN c.stato = 'Da contattare' THEN 1 END) AS da_contattare,
            COUNT(CASE WHEN c.stato = 'Risposto' THEN 1 END)      AS risposto,
            COUNT(CASE WHEN c.stato = 'In valutazione' THEN 1 END) AS in_valutazione,
            AVG(c.punteggio)                                     AS punteggio_medio,
            MAX(c.data_aggiornamento)                            AS ultimo_aggiornamento
        FROM profili_target pt
        JOIN candidati c ON c.profilo_target_id = pt.id
            AND c.organizzazione_id = ?
        WHERE pt.organizzazione_id = ?
        GROUP BY pt.id
        ORDER BY MAX(c.data_aggiornamento) DESC
    """, (org_id, org_id)).fetchall()

    candidati_senza_profilo = db.execute("""
        SELECT COUNT(*) AS totale FROM candidati
        WHERE organizzazione_id = ?
          AND (profilo_target_id IS NULL OR profilo_target_id = 0)
    """, (org_id,)).fetchone()

    db.close()

    return render_template(
        "pipeline_grid.html",
        pipeline=pipeline_per_profilo,
        senza_profilo=candidati_senza_profilo["totale"] if candidati_senza_profilo else 0,
    )


@pipeline_bp.route("/pipeline/profilo/<int:profilo_id>")
def profilo_detail(profilo_id):
    """Pipeline filtrata per un profilo target specifico."""
    tab = request.args.get("tab", "pipeline")
    if tab not in ("pipeline", "calendario", "cronologia"):
        tab = "pipeline"

    org_id = get_org_id()
    db = get_db()

    # Info profilo target (0 = senza profilo)
    profilo_target = None
    if profilo_id > 0:
        profilo_target = db.execute(
            "SELECT * FROM profili_target WHERE id = ? AND organizzazione_id = ?",
            (profilo_id, org_id)
        ).fetchone()
        if profilo_target:
            profilo_target = dict(profilo_target)

    # Candidati filtrati per profilo_target_id
    if profilo_id > 0:
        candidati = db.execute(
            "SELECT * FROM candidati WHERE organizzazione_id = ? AND profilo_target_id = ? ORDER BY data_aggiornamento DESC",
            (org_id, profilo_id)
        ).fetchall()
    else:
        candidati = db.execute(
            "SELECT * FROM candidati WHERE organizzazione_id = ? AND (profilo_target_id IS NULL OR profilo_target_id = 0) ORDER BY data_aggiornamento DESC",
            (org_id,)
        ).fetchall()

    candidati_lista = [dict(c) for c in candidati]
    for c in candidati_lista:
        if c.get("spunti"):
            try:
                c["spunti"] = json.loads(c["spunti"])
            except Exception:
                c["spunti"] = []

    # Prossimo appuntamento per ogni candidato
    prossimi_app = {}
    try:
        righe = db.execute(
            """SELECT candidato_id, MIN(data_ora) as prossimo
               FROM appuntamenti
               WHERE stato = 'Da fare' AND data_ora >= CURRENT_TIMESTAMP
               GROUP BY candidato_id"""
        ).fetchall()
        for r in righe:
            prossimi_app[r['candidato_id']] = r['prossimo']
    except Exception:
        pass

    # Cronologia valutazioni
    cronologia = db.execute(
        "SELECT * FROM valutazioni WHERE organizzazione_id = ? ORDER BY data_valutazione DESC",
        (org_id,)
    ).fetchall()
    cronologia = [dict(r) for r in cronologia]

    # Appuntamenti
    appuntamenti = db.execute("""
        SELECT a.*,
               COALESCE(c.nome || ' ' || c.cognome, 'Candidato rimosso') AS candidato_nome
        FROM appuntamenti a
        LEFT JOIN candidati c ON a.candidato_id = c.id
        WHERE a.organizzazione_id = ?
        ORDER BY a.data_ora ASC
    """, (org_id,)).fetchall()
    appuntamenti = [dict(a) for a in appuntamenti]

    db.close()

    return render_template(
        "pipeline.html",
        candidati=candidati_lista,
        stati=STATI_VALIDI,
        gestori=GESTORI_VALIDI,
        prossimi_app=prossimi_app,
        cronologia=cronologia,
        appuntamenti=appuntamenti,
        tipi_app=TIPI_APPUNTAMENTO,
        gestori_cal=GESTORI_CAL,
        stati_app=STATI_APPUNTAMENTO,
        tab_attivo=tab,
        profilo_target=profilo_target,
        profilo_id=profilo_id,
    )


@pipeline_bp.route("/pipeline/aggiorna_stato", methods=["POST"])
def aggiorna_stato():
    """Endpoint AJAX per aggiornare lo stato di un candidato."""
    dati = request.get_json()
    candidato_id = dati.get("id")
    nuovo_stato = dati.get("stato")

    if nuovo_stato not in STATI_VALIDI:
        return jsonify({"errore": "Stato non valido"}), 400

    org_id = get_org_id()
    db = get_db()
    db.execute(
        "UPDATE candidati SET stato = ?, data_aggiornamento = CURRENT_TIMESTAMP WHERE id = ? AND organizzazione_id = ?",
        (nuovo_stato, candidato_id, org_id),
    )
    db.commit()
    db.close()

    return jsonify({"successo": True, "stato": nuovo_stato})


@pipeline_bp.route("/pipeline/aggiorna_gestore", methods=["POST"])
def aggiorna_gestore():
    """Endpoint AJAX per aggiornare il gestore di un candidato."""
    dati = request.get_json()
    candidato_id = dati.get("id")
    nuovo_gestore = dati.get("gestore")

    if nuovo_gestore not in GESTORI_VALIDI:
        return jsonify({"errore": "Gestore non valido"}), 400

    org_id = get_org_id()
    db = get_db()
    db.execute(
        "UPDATE candidati SET gestore = ?, data_aggiornamento = CURRENT_TIMESTAMP WHERE id = ? AND organizzazione_id = ?",
        (nuovo_gestore, candidato_id, org_id),
    )
    db.commit()
    db.close()

    return jsonify({"successo": True, "gestore": nuovo_gestore})


@pipeline_bp.route("/pipeline/followup/<int:candidato_id>", methods=["POST"])
def genera_followup(candidato_id):
    """Endpoint AJAX per generare un messaggio di follow-up con AI."""
    org_id = get_org_id()
    db = get_db()
    row = db.execute(
        "SELECT * FROM candidati WHERE id = ? AND organizzazione_id = ?", (candidato_id, org_id)
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

    org_id = get_org_id()
    db = get_db()
    row = db.execute(
        "SELECT * FROM candidati WHERE id = ? AND organizzazione_id = ?", (candidato_id, org_id)
    ).fetchone()
    db.close()

    if not row:
        return jsonify({"errore": "Candidato non trovato"}), 404

    messaggio = rigenera_messaggio_followup(dict(row), messaggio_attuale, istruzioni)
    return jsonify({"messaggio": messaggio})


@pipeline_bp.route("/pipeline/<int:candidato_id>/note", methods=["PATCH"])
def aggiorna_note(candidato_id):
    """Endpoint AJAX per aggiornare le note di un candidato."""
    dati = request.get_json()
    note = dati.get("note", "")
    org_id = get_org_id()
    db = get_db()
    db.execute(
        "UPDATE candidati SET note = ?, data_aggiornamento = CURRENT_TIMESTAMP WHERE id = ? AND organizzazione_id = ?",
        (note, candidato_id, org_id),
    )
    db.commit()
    db.close()
    return jsonify({"successo": True})


@pipeline_bp.route("/pipeline/elimina/<int:candidato_id>", methods=["DELETE"])
def elimina_candidato(candidato_id):
    """Elimina un candidato dalla pipeline."""
    org_id = get_org_id()
    db = get_db()
    db.execute("DELETE FROM candidati WHERE id = ? AND organizzazione_id = ?", (candidato_id, org_id))
    db.commit()
    db.close()
    return jsonify({"successo": True})
