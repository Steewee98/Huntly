"""
Recruiter Assistant — Applicazione principale Flask.
Entry point dell'app, registra tutti i blueprint e inizializza il database.
"""

import os
from flask import Flask, redirect, url_for
from dotenv import load_dotenv
from database import init_db
from routes.auth import auth_bp, login_required
from routes.valutazione import valutazione_bp
from routes.candidati import candidati_bp
from routes.pipeline import pipeline_bp
from routes.contenuti import contenuti_bp
from routes.ricerca import ricerca_bp
from routes.impostazioni import impostazioni_bp

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

# Proteggi tutte le view con login_required (eccetto auth)
for bp in [valutazione_bp, candidati_bp, pipeline_bp, contenuti_bp, ricerca_bp, impostazioni_bp]:
    for endpoint, view_func in app.view_functions.items():
        if endpoint.startswith(bp.name + "."):
            app.view_functions[endpoint] = login_required(view_func)


@app.route("/")
@login_required
def home():
    """Reindirizza alla pagina di valutazione candidati come homepage."""
    return redirect(url_for("valutazione.index"))


# Inizializza il database all'avvio dell'app
with app.app_context():
    init_db()


if __name__ == "__main__":
    # Avvia il server in modalità debug per lo sviluppo
    app.run(debug=True, port=5001)
