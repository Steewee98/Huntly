"""
Modulo Profili Target — gestione CRUD dei profili di ricerca configurabili.
Sostituisce il sistema fisso Profilo A / Profilo B con profili personalizzabili.
"""

import json

from flask import Blueprint, jsonify, render_template, request
from database import get_db
from routes.auth import get_org_id, login_required

profili_bp = Blueprint("profili", __name__)

_COLORI_DEFAULT = ['#6366f1', '#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#be185d']


@profili_bp.route("/profili")
def index():
    org_id = get_org_id()
    db = get_db()
    profili = db.execute(
        "SELECT * FROM profili_target WHERE attivo = TRUE AND organizzazione_id = ? ORDER BY creato_il",
        (org_id,)
    ).fetchall()
    db.close()
    return render_template("profili.html", profili=[dict(p) for p in profili],
                           colori=_COLORI_DEFAULT)


@profili_bp.route("/profili/lista")
def lista():
    """API JSON: lista profili attivi (usata da ricerca.html)."""
    org_id = get_org_id()
    db = get_db()
    profili = db.execute(
        "SELECT id, nome, descrizione, colore FROM profili_target WHERE attivo = TRUE AND organizzazione_id = ? ORDER BY creato_il",
        (org_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(p) for p in profili])


@profili_bp.route("/profili/<int:pid>")
def dettaglio(pid):
    org_id = get_org_id()
    db = get_db()
    p = db.execute(
        "SELECT * FROM profili_target WHERE id = ? AND organizzazione_id = ?", (pid, org_id)
    ).fetchone()
    db.close()
    if not p:
        return jsonify({"errore": "Profilo non trovato"}), 404
    return jsonify(dict(p))


@profili_bp.route("/profili", methods=["POST"])
def crea():
    d = request.get_json() or {}
    org_id = get_org_id()
    db = get_db()
    db.execute(
        """INSERT INTO profili_target
           (nome, descrizione, ruoli_target, settori, eta_min, eta_max,
            anni_esperienza_min, keyword_positive, keyword_negative, colore,
            scopo, scopo_dettaglio, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            (d.get("nome") or "").strip(),
            (d.get("descrizione") or "").strip(),
            (d.get("ruoli_target") or "").strip(),
            (d.get("settori") or "").strip(),
            int(d.get("eta_min") or 0),
            int(d.get("eta_max") or 99),
            int(d.get("anni_esperienza_min") or 0),
            (d.get("keyword_positive") or "").strip(),
            (d.get("keyword_negative") or "").strip(),
            (d.get("colore") or "#6366f1").strip(),
            (d.get("scopo") or "recruiting").strip(),
            (d.get("scopo_dettaglio") or "").strip(),
            org_id,
        )
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@profili_bp.route("/profili/<int:pid>", methods=["PUT"])
def modifica(pid):
    d = request.get_json() or {}
    org_id = get_org_id()
    db = get_db()
    db.execute(
        """UPDATE profili_target SET
           nome=?, descrizione=?, ruoli_target=?, settori=?,
           eta_min=?, eta_max=?, anni_esperienza_min=?,
           keyword_positive=?, keyword_negative=?, colore=?,
           scopo=?, scopo_dettaglio=?
           WHERE id=? AND organizzazione_id=?""",
        (
            (d.get("nome") or "").strip(),
            (d.get("descrizione") or "").strip(),
            (d.get("ruoli_target") or "").strip(),
            (d.get("settori") or "").strip(),
            int(d.get("eta_min") or 0),
            int(d.get("eta_max") or 99),
            int(d.get("anni_esperienza_min") or 0),
            (d.get("keyword_positive") or "").strip(),
            (d.get("keyword_negative") or "").strip(),
            (d.get("colore") or "#6366f1").strip(),
            (d.get("scopo") or "recruiting").strip(),
            (d.get("scopo_dettaglio") or "").strip(),
            pid,
            org_id,
        )
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@profili_bp.route("/profili/auto-compila", methods=["POST"])
@login_required
def auto_compila():
    dati = request.get_json()
    descrizione = (dati.get("descrizione") or "").strip()
    if not descrizione:
        return jsonify({"errore": "Descrizione vuota"}), 400

    prompt = f"""Analizza questa descrizione di un profilo target per una ricerca professionale e estrai i parametri strutturati.

Descrizione: {descrizione}

Restituisci SOLO un JSON valido con questi campi:
{{
  "nome": "nome breve del profilo (3-5 parole)",
  "ruoli_target": "lista ruoli separati da virgola",
  "settori": "lista settori separati da virgola",
  "anni_esperienza_min": numero intero (0 se non specificato),
  "keyword_positive": "keyword rilevanti separate da virgola",
  "keyword_negative": "keyword da escludere separate da virgola (vuoto se non specificato)",
  "scopo": "recruiting|sales|partnership|network",
  "scopo_dettaglio": "descrizione dettagliata dello scopo"
}}

Sii preciso e conciso. Solo JSON, nessun testo aggiuntivo."""

    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    testo = response.content[0].text.strip()
    testo = testo.replace('```json', '').replace('```', '').strip()
    risultato = json.loads(testo)
    return jsonify(risultato)


@profili_bp.route("/profili/<int:pid>", methods=["DELETE"])
def elimina(pid):
    org_id = get_org_id()
    db = get_db()
    db.execute("DELETE FROM profili_target WHERE id = ? AND organizzazione_id = ?", (pid, org_id))
    db.commit()
    db.close()
    return jsonify({"ok": True})
