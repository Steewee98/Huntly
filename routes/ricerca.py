"""
Modulo 5 — Ricerca Automatica Candidati via Apify (LinkedIn Profile Search).
Cerca figure professionali su LinkedIn tramite l'actor harvestapi/linkedin-profile-search
e le importa nella pipeline.
"""

import os
import time
import requests
from flask import Blueprint, render_template, request, jsonify
from database import get_db
from ai_helpers import analizza_profilo_linkedin

# Blueprint per il modulo ricerca
ricerca_bp = Blueprint("ricerca", __name__)

# Actor Apify per la ricerca persone su LinkedIn (no cookies richiesti)
APIFY_ACTOR = "harvestapi~linkedin-profile-search"
APIFY_BASE  = "https://api.apify.com/v2"


def cerca_apify(ruolo, citta="", paese="", azienda="", parole_chiave="", num_pagine=1):
    """
    Avvia una run dell'actor Apify e attende i risultati.
    Restituisce (lista_profili, errore).
    """
    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        return None, "APIFY_API_KEY non configurata nel file .env"

    # Costruisce l'input dell'actor
    run_input = {
        "takePages": num_pagine,
        "startPage": 1,
    }

    if ruolo:
        run_input["currentJobTitles"] = [ruolo]
    if parole_chiave:
        run_input["keywords"] = parole_chiave
    if citta or paese:
        location = ", ".join(filter(None, [citta, paese]))
        run_input["locations"] = [location]
    if azienda:
        run_input["currentCompanies"] = [azienda]

    try:
        # Avvia la run in modalità sincrona (attende max 120s e restituisce il dataset)
        resp = requests.post(
            f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items",
            json=run_input,
            params={"token": api_key, "timeout": 120},
            timeout=130,
        )
        resp.raise_for_status()
        items = resp.json()

        # L'endpoint può restituire una lista diretta o un oggetto con "items"
        if isinstance(items, list):
            return items, None
        if isinstance(items, dict):
            return items.get("items", []), None
        return [], None

    except requests.exceptions.HTTPError:
        return None, f"Errore API Apify: {resp.status_code} — {resp.text[:300]}"
    except requests.exceptions.RequestException as e:
        return None, f"Errore di connessione: {str(e)}"


def normalizza_profilo(p):
    """Estrae i campi utili da un profilo restituito dall'actor."""
    # L'actor può usare campi leggermente diversi a seconda della versione
    nome    = p.get("firstName") or p.get("first_name") or ""
    cognome = p.get("lastName")  or p.get("last_name")  or ""
    ruolo   = (p.get("headline") or p.get("title") or p.get("occupation") or "")

    # Azienda corrente
    azienda = ""
    posizione_corrente = p.get("currentPositions") or p.get("positions") or []
    if posizione_corrente and isinstance(posizione_corrente, list):
        prima = posizione_corrente[0]
        azienda = prima.get("companyName") or prima.get("company") or ""
        if not ruolo:
            ruolo = prima.get("title") or ""

    # Fallback azienda da campo diretto
    if not azienda:
        azienda = p.get("companyName") or p.get("company") or ""

    location = p.get("location") or p.get("geoLocation") or ""
    linkedin  = p.get("linkedinUrl") or p.get("profileUrl") or p.get("url") or ""
    summary   = (p.get("summary") or p.get("about") or "")[:200]

    return {
        "nome":     nome,
        "cognome":  cognome,
        "ruolo":    ruolo,
        "azienda":  azienda,
        "location": location,
        "linkedin": linkedin,
        "headline": ruolo,
        "sommario": summary,
    }


@ricerca_bp.route("/ricerca")
def index():
    """Pagina di ricerca automatica figure con Apify/LinkedIn."""
    db = get_db()
    imp_a = db.execute("SELECT id FROM impostazioni_profilo WHERE profilo='A'").fetchone()
    imp_b = db.execute("SELECT id FROM impostazioni_profilo WHERE profilo='B'").fetchone()
    db.close()
    return render_template("ricerca.html",
                           imp_a_configurato=imp_a is not None,
                           imp_b_configurato=imp_b is not None)


@ricerca_bp.route("/ricerca/cerca", methods=["POST"])
def cerca():
    """Esegue la ricerca su Apify e restituisce i risultati normalizzati."""
    dati = request.get_json()
    ruolo        = dati.get("ruolo", "").strip()
    citta        = dati.get("citta", "").strip()
    paese        = dati.get("paese", "").strip()
    azienda      = dati.get("azienda", "").strip()
    parole_chiave = dati.get("parole_chiave", "").strip()
    num_pagine   = int(dati.get("num_pagine", 1))

    if not ruolo and not parole_chiave:
        return jsonify({"errore": "Inserisci almeno il ruolo o delle parole chiave"}), 400

    items, errore = cerca_apify(ruolo, citta, paese, azienda, parole_chiave, num_pagine)
    if errore:
        return jsonify({"errore": errore}), 500

    persone = [normalizza_profilo(p) for p in items if isinstance(p, dict)]

    return jsonify({
        "persone": persone,
        "totale": len(persone),
    })


@ricerca_bp.route("/ricerca/automatica", methods=["POST"])
def automatica():
    """
    Ricerca automatica basata sui parametri delle impostazioni.
    Importa i candidati trovati e lancia la valutazione AI per ciascuno.
    """
    dati = request.get_json()
    tipo_profilo = dati.get("tipo_profilo", "A")
    max_profili  = max(1, min(int(dati.get("max_profili", 20)), 100))

    # Leggi impostazioni del profilo selezionato
    db = get_db()
    imp_row = db.execute(
        "SELECT * FROM impostazioni_profilo WHERE profilo = ?", (tipo_profilo,)
    ).fetchone()
    db.close()

    if not imp_row:
        return jsonify({"errore": f"Impostazioni Profilo {tipo_profilo} non ancora configurate. "
                                  f"Vai in Impostazioni e salva i parametri prima di usare la ricerca automatica."}), 400

    imp = dict(imp_row)

    # Costruisci la query per Apify dai parametri delle impostazioni
    ruoli_raw = imp.get("ruoli_target", "") or ""
    ruoli = [r.strip() for r in ruoli_raw.split(",") if r.strip()]

    kw_positive = imp.get("keyword_positive", "") or ""
    if tipo_profilo == "A":
        extra = imp.get("settori", "") or ""
    else:
        extra = imp.get("istituti", "") or ""

    kw_parts = [k.strip() for k in kw_positive.split(",") if k.strip()]
    kw_parts += [s.strip() for s in extra.split(",") if s.strip()]
    keywords = " ".join(kw_parts[:6])

    ruolo_principale = ruoli[0] if ruoli else ""

    # Calcola numero pagine (Apify restituisce ~10 profili per pagina)
    num_pagine = max(1, (max_profili + 9) // 10)

    items, errore = cerca_apify(ruolo_principale, "", "", "", keywords, num_pagine)
    if errore:
        return jsonify({"errore": errore}), 500

    items = items[:max_profili]
    trovati  = len(items)
    importati = 0
    valutati  = 0
    punteggi  = []

    db = get_db()
    for item in items:
        p = normalizza_profilo(item)
        if not p["nome"] and not p["cognome"]:
            continue

        # Importa nella pipeline con stato "Da valutare"
        cur = db.execute(
            """INSERT INTO candidati
               (nome, cognome, ruolo_attuale, azienda, profilo_linkedin,
                tipo_profilo, stato, note)
               VALUES (?, ?, ?, ?, ?, ?, 'Da valutare', ?)""",
            (p["nome"], p["cognome"], p["ruolo"], p["azienda"],
             p["linkedin"], tipo_profilo, p["headline"])
        )
        db.commit()
        candidato_id = cur.lastrowid
        importati += 1

        # Valutazione AI con i parametri delle impostazioni
        try:
            testo = (
                f"Nome: {p['nome']} {p['cognome']}\n"
                f"Ruolo: {p['ruolo']}\n"
                f"Azienda: {p['azienda']}\n"
                f"Location: {p['location']}\n"
                f"Sommario: {p['sommario']}\n"
            )
            risultato = analizza_profilo_linkedin(testo, tipo_profilo, imp)
            punteggio = risultato.get("punteggio")
            db.execute(
                """UPDATE candidati SET
                   punteggio=?, analisi=?, spunti=?, messaggio_outreach=?,
                   stato='Da contattare', data_aggiornamento=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (punteggio,
                 risultato.get("analisi_percorso", ""),
                 str(risultato.get("spunti_contatto", [])),
                 risultato.get("messaggio_outreach", ""),
                 candidato_id)
            )
            db.commit()
            valutati += 1
            if punteggio:
                punteggi.append(punteggio)
        except Exception:
            pass  # continua anche se l'analisi AI fallisce per un singolo candidato

    db.close()

    punteggio_medio = round(sum(punteggi) / len(punteggi), 1) if punteggi else None
    return jsonify({
        "successo": True,
        "trovati":  trovati,
        "importati": importati,
        "valutati":  valutati,
        "punteggio_medio": punteggio_medio,
    })


@ricerca_bp.route("/ricerca/importa", methods=["POST"])
def importa():
    """Salva un candidato trovato nella ricerca nel database."""
    dati = request.get_json()
    nome         = dati.get("nome", "").strip()
    cognome      = dati.get("cognome", "").strip()
    ruolo_attuale = dati.get("ruolo", "").strip()
    azienda      = dati.get("azienda", "").strip()
    linkedin     = dati.get("linkedin", "").strip()
    tipo_profilo = dati.get("tipo_profilo", "A")
    note         = dati.get("headline", "").strip()

    if not nome and not cognome:
        return jsonify({"errore": "Nome o cognome mancante"}), 400

    db = get_db()
    cur = db.execute(
        """INSERT INTO candidati
           (nome, cognome, ruolo_attuale, azienda, profilo_linkedin, tipo_profilo, note)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (nome, cognome, ruolo_attuale, azienda, linkedin, tipo_profilo, note),
    )
    db.commit()
    nuovo_id = cur.lastrowid
    db.close()

    return jsonify({"successo": True, "candidato_id": nuovo_id})
