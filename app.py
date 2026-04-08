"""
Recruiter Assistant — Applicazione principale Flask.
Entry point dell'app, registra tutti i blueprint e inizializza il database.
"""

import os
from flask import Flask, redirect, url_for, jsonify
from ai_helpers import test_connessione_api, CLAUDE_MODEL
from dotenv import load_dotenv
from database import init_db, get_db
from routes.auth import auth_bp, login_required
from routes.valutazione import valutazione_bp
from routes.candidati import candidati_bp
from routes.pipeline import pipeline_bp
from routes.contenuti import contenuti_bp
from routes.ricerca import ricerca_bp
from routes.impostazioni import impostazioni_bp
from routes.calendario import calendario_bp

# Carica le variabili d'ambiente dal file .env (se presente)
load_dotenv()

# Crea l'applicazione Flask
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "recruiter-assistant-secret-2024")

# Registra i blueprint
app.register_blueprint(auth_bp)
app.register_blueprint(valutazione_bp)
app.register_blueprint(candidati_bp)
app.register_blueprint(pipeline_bp)
app.register_blueprint(contenuti_bp)
app.register_blueprint(ricerca_bp)
app.register_blueprint(impostazioni_bp)
app.register_blueprint(calendario_bp)

# Proteggi tutte le view con login_required (eccetto auth)
for bp in [valutazione_bp, candidati_bp, pipeline_bp, contenuti_bp, ricerca_bp, impostazioni_bp, calendario_bp]:
    for endpoint, view_func in app.view_functions.items():
        if endpoint.startswith(bp.name + "."):
            app.view_functions[endpoint] = login_required(view_func)


@app.after_request
def add_cache_headers(response):
    """Aggiunge cache headers ai file statici per ridurre le richieste al server."""
    from flask import request as flask_req
    if flask_req.path.startswith("/static/"):
        # 1 anno per file statici (CSS, JS, immagini): cambiano raramente
        response.cache_control.max_age = 31536000
        response.cache_control.public = True
    return response


@app.route("/")
@login_required
def home():
    """Reindirizza alla pagina di valutazione candidati come homepage."""
    return redirect(url_for("valutazione.index"))


# Inizializza il database all'avvio dell'app
with app.app_context():
    try:
        init_db()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("ERRORE INIT DB: %s", e, exc_info=True)
        print(f"ERRORE INIT DB: {e}")


@app.route("/admin/init-db")
def admin_init_db():
    """
    Esegue init_db() manualmente e crea tutte le tabelle mancanti.
    Sicuro da chiamare più volte (usa IF NOT EXISTS ovunque).
    Utile dopo aver aggiunto il database PostgreSQL su Railway.
    """
    try:
        init_db()
        # Verifica quali tabelle esistono dopo l'inizializzazione
        db = get_db()
        tabelle = db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()
        db.close()
        nomi = [t["table_name"] for t in tabelle]
        return jsonify({
            "successo": True,
            "messaggio": "Database inizializzato correttamente.",
            "tabelle_create": nomi
        })
    except Exception as e:
        return jsonify({
            "successo": False,
            "errore": str(e)
        }), 500


@app.errorhandler(Exception)
def handle_exception(e):
    """
    Restituisce sempre JSON invece di HTML in caso di errore non gestito.
    Evita il SyntaxError di Safari quando il browser si aspetta JSON ma riceve HTML.
    """
    import traceback, logging
    logging.getLogger(__name__).error("Unhandled exception: %s", traceback.format_exc())
    from flask import request as flask_request
    # Restituisce JSON per tutte le chiamate AJAX/fetch:
    # - Content-Type: application/json (POST con corpo JSON)
    # - X-Requested-With: XMLHttpRequest (jQuery legacy)
    # - Accept: application/json
    # - Metodi non-GET senza HTML nel Accept (DELETE, PUT, PATCH)
    is_ajax = (
        flask_request.is_json
        or flask_request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in flask_request.headers.get("Accept", "")
        or flask_request.method in ("DELETE", "PUT", "PATCH")
    )
    if is_ajax:
        return jsonify({"errore": str(e), "tipo": type(e).__name__}), 500
    # Per pagine HTML rilancia l'eccezione normale di Flask
    raise e


@app.route("/admin/test-api")
def admin_test_api():
    """Verifica la connessione all'API Anthropic con una chiamata minimale."""
    risultato = test_connessione_api()
    risultato["model_usato"] = CLAUDE_MODEL
    return jsonify(risultato), 200 if risultato["ok"] else 500


if __name__ == "__main__":
    # Avvia il server in modalità debug per lo sviluppo
    app.run(debug=True, port=5001)
