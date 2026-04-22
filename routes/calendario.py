"""
Modulo Calendario — Gestione appuntamenti con i candidati.
"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from database import get_db

calendario_bp = Blueprint('calendario', __name__)

TIPI_APPUNTAMENTO = ['Chiamata', 'Video call', 'Incontro di persona']
GESTORI = ['Admin', 'Recruiter']
STATI_APPUNTAMENTO = ['Da fare', 'Completato', 'Annullato']


@calendario_bp.route('/calendario')
def index():
    """Redirect alla pipeline con tab calendario."""
    params = {k: v for k, v in request.args.items()}
    params['tab'] = 'calendario'
    return redirect(url_for('pipeline.index', **params))


@calendario_bp.route('/calendario/nuovo', methods=['POST'])
def nuovo():
    dati = request.get_json()
    candidato_id = dati.get('candidato_id') or None
    gestore = dati.get('gestore', '').strip()
    tipo = dati.get('tipo', '').strip()
    data_ora = dati.get('data_ora', '').strip()
    note = dati.get('note', '').strip()
    stato = dati.get('stato', 'Da fare').strip()

    if not gestore or not tipo or not data_ora:
        return jsonify({'errore': 'Gestore, tipo e data/ora sono obbligatori'}), 400

    try:
        dt = datetime.strptime(data_ora, '%Y-%m-%dT%H:%M')
        data_ora_db = dt.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        data_ora_db = data_ora

    db = get_db()
    cur = db.execute(
        """INSERT INTO appuntamenti (candidato_id, gestore, tipo, data_ora, note, stato)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (candidato_id, gestore, tipo, data_ora_db, note, stato)
    )
    db.commit()
    nuovo_id = cur.lastrowid
    db.close()

    return jsonify({'successo': True, 'id': nuovo_id})


@calendario_bp.route('/calendario/aggiorna/<int:app_id>', methods=['POST'])
def aggiorna(app_id):
    dati = request.get_json()
    candidato_id = dati.get('candidato_id') or None
    gestore = dati.get('gestore', '').strip()
    tipo = dati.get('tipo', '').strip()
    data_ora = dati.get('data_ora', '').strip()
    note = dati.get('note', '').strip()
    stato = dati.get('stato', 'Da fare').strip()

    try:
        dt = datetime.strptime(data_ora, '%Y-%m-%dT%H:%M')
        data_ora_db = dt.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        data_ora_db = data_ora

    db = get_db()
    db.execute(
        """UPDATE appuntamenti
           SET candidato_id=?, gestore=?, tipo=?, data_ora=?, note=?, stato=?
           WHERE id=?""",
        (candidato_id, gestore, tipo, data_ora_db, note, stato, app_id)
    )
    db.commit()
    db.close()
    return jsonify({'successo': True})


@calendario_bp.route('/calendario/elimina/<int:app_id>', methods=['DELETE'])
def elimina(app_id):
    db = get_db()
    db.execute("DELETE FROM appuntamenti WHERE id = ?", (app_id,))
    db.commit()
    db.close()
    return jsonify({'successo': True})


@calendario_bp.route('/calendario/prossimi')
def prossimi():
    """Appuntamenti nelle prossime 24 ore — usato per il banner promemoria."""
    db = get_db()
    now = datetime.now()
    domani = now + timedelta(hours=24)

    rows = db.execute(
        """SELECT a.id, a.tipo, a.data_ora, a.gestore,
                  COALESCE(c.nome || ' ' || c.cognome, '') AS candidato_nome
           FROM appuntamenti a
           LEFT JOIN candidati c ON a.candidato_id = c.id
           WHERE a.stato = 'Da fare'
             AND a.data_ora >= ?
             AND a.data_ora <= ?
           ORDER BY a.data_ora ASC""",
        (now.strftime('%Y-%m-%d %H:%M:%S'), domani.strftime('%Y-%m-%d %H:%M:%S'))
    ).fetchall()
    db.close()

    return jsonify({
        'totale': len(rows),
        'appuntamenti': [dict(r) for r in rows]
    })
