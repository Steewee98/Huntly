"""
Modulo 5 — Ricerca Automatica Candidati via Apify (LinkedIn Profile Search).
Cerca figure professionali su LinkedIn tramite l'actor harvestapi/linkedin-profile-search
e le importa nella pipeline.
"""

import io
import csv
import concurrent.futures
import json
import os
import time
import threading
import uuid
import requests
from flask import Blueprint, render_template, request, jsonify, Response
from database import get_db
from ai_helpers import analizza_profilo_linkedin

# Blueprint per il modulo ricerca
ricerca_bp = Blueprint("ricerca", __name__)

# Actor Apify per la ricerca persone su LinkedIn (no cookies richiesti)
APIFY_ACTOR = "harvestapi~linkedin-profile-search"
APIFY_BASE  = "https://api.apify.com/v2"


def cerca_apify(ruolo, citta="", paese="", azienda="", parole_chiave="", num_pagine=1,
                ruoli_lista=None, forza_italia=True):
    """
    Avvia una run dell'actor Apify e attende i risultati.
    ruoli_lista: lista di titoli alternativi (usa al posto di ruolo se fornita).
    forza_italia: se True e nessuna città/paese specificato, aggiunge Italy come filtro.
    Restituisce (lista_profili, errore).
    """
    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        return None, "APIFY_API_KEY non configurata nel file .env"

    run_input = {
        "takePages": num_pagine,
        "startPage": 1,
    }

    # Titoli di lavoro correnti — usa lista se fornita, altrimenti singolo ruolo
    titoli = [r for r in ruoli_lista if r][:5] if ruoli_lista else ([ruolo] if ruolo else [])
    if titoli:
        run_input["currentJobTitles"] = titoli

    # Keywords: combina ruoli + parole_chiave per migliorare la copertura di ricerca
    kw_parts = []
    if titoli:
        kw_parts.append(" OR ".join(f'"{t}"' for t in titoli[:3]))
    if parole_chiave:
        kw_parts.append(parole_chiave)
    if kw_parts:
        run_input["keywords"] = " ".join(kw_parts)

    # Location: sempre Italia se non specificato (migliora rilevanza risultati)
    if citta or paese:
        run_input["locations"] = [", ".join(filter(None, [citta, paese]))]
    elif forza_italia:
        run_input["locations"] = ["Italy"]

    if azienda:
        run_input["currentCompanies"] = [azienda]

    try:
        resp = requests.post(
            f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items",
            json=run_input,
            params={"token": api_key, "timeout": 120},
            timeout=130,
        )
        resp.raise_for_status()
        items = resp.json()

        if isinstance(items, list):
            return items, None
        if isinstance(items, dict):
            return items.get("items", []), None
        return [], None

    except requests.exceptions.HTTPError:
        return None, f"Errore API Apify: {resp.status_code} — {resp.text[:300]}"
    except requests.exceptions.RequestException as e:
        return None, f"Errore di connessione: {str(e)}"


def _str(val) -> str:
    """
    Converte qualsiasi valore in stringa sicura per il database.
    Gestisce i casi in cui Apify restituisce oggetti annidati invece di stringhe:
    - dict con chiave "linkedinText", "name", "text" → estrae il testo
    - list → join con virgola
    - None / bool → stringa vuota o repr
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        # Apify spesso restituisce {"linkedinText": "...", "text": "..."}
        for key in ("linkedinText", "text", "name", "value", "title"):
            if val.get(key) and isinstance(val[key], str):
                return val[key]
        return ""
    if isinstance(val, list):
        return ", ".join(_str(v) for v in val if v)
    return str(val)


def _costruisci_testo_profilo(p):
    """Costruisce il testo completo del profilo da usare per l'analisi AI e per la visualizzazione."""
    parti = [
        f"Nome: {_str(p.get('nome'))} {_str(p.get('cognome'))}".strip(),
        f"Ruolo: {_str(p.get('ruolo'))}",
        f"Azienda: {_str(p.get('azienda'))}",
        f"Location: {_str(p.get('location'))}",
    ]
    if p.get("sommario"):
        parti.append(f"Sommario: {_str(p['sommario'])}")
    if p.get("linkedin"):
        parti.append(f"LinkedIn: {_str(p['linkedin'])}")
    return "\n".join(parti)


# Termini che indicano location italiana (usati da _filtro_qualita)
_LOCATION_ITALIANE = {
    'italy', 'italia', 'milan', 'milano', 'roma', 'rome', 'napoli', 'naples',
    'torino', 'turin', 'firenze', 'florence', 'bologna', 'venezia', 'venice',
    'genova', 'genoa', 'palermo', 'bari', 'catania', 'verona', 'padova',
    'trieste', 'brescia', 'parma', 'modena', 'reggio', 'perugia', 'siena',
    'trento', 'trentino', 'sardegna', 'sicilia', 'lombardia', 'piemonte',
    'toscana', 'veneto', 'lazio', 'campania', 'puglia', 'calabria',
}


def _filtro_qualita(p: dict) -> tuple:
    """
    Scarta profili senza dati essenziali o non italiani.
    Va applicato PRIMA di _filtro_locale per eliminare il rumore di Apify.
    Ritorna (passa: bool, motivo_scarto: str).
    """
    # 1. Senza nome
    if not p.get('nome') and not p.get('cognome'):
        return False, "Senza nome"

    # 2. Senza ruolo attuale
    if not p.get('ruolo'):
        return False, "Senza ruolo attuale"

    # 3. Testo totale insufficiente
    testo = " ".join(filter(None, [
        p.get('nome', ''), p.get('cognome', ''), p.get('ruolo', ''),
        p.get('azienda', ''), p.get('sommario', ''),
    ]))
    if len(testo) < 50:
        return False, "Profilo incompleto (< 50 caratteri)"

    # 4. Location presente ma chiaramente non italiana
    location = (p.get('location') or '').lower()
    if location and not any(t in location for t in _LOCATION_ITALIANE):
        return False, f"Location non italiana: {p.get('location', '')[:40]}"

    return True, ""


def _controlla_duplicato(db, p: dict) -> bool:
    """
    Controlla se il profilo esiste già in candidati.
    Prima verifica l'URL LinkedIn; fallback su nome + cognome + azienda.
    Ritorna True se duplicato.
    """
    linkedin = (p.get('linkedin') or '').strip()
    if linkedin:
        row = db.execute(
            "SELECT id FROM candidati WHERE profilo_linkedin = ?", (linkedin,)
        ).fetchone()
        if row:
            return True

    # Fallback nome + cognome + azienda (case-insensitive)
    nome    = (p.get('nome', '') or '').strip().lower()
    cognome = (p.get('cognome', '') or '').strip().lower()
    azienda = (p.get('azienda', '') or '').strip().lower()
    if nome and cognome and azienda:
        row = db.execute(
            "SELECT id FROM candidati WHERE LOWER(nome)=? AND LOWER(cognome)=? AND LOWER(azienda)=?",
            (nome, cognome, azienda)
        ).fetchone()
        if row:
            return True

    return False


def _filtro_locale(p: dict, imp: dict) -> tuple:
    """
    Filtra velocemente un profilo normalizzato contro le impostazioni configurate.
    Non fa chiamate API — solo string matching locale.
    Ritorna (passa: bool, motivo_scarto: str).
    Più permissivo che restrittivo: se le impostazioni sono vuote, tutto passa.
    """
    testo = " ".join(filter(None, [
        str(p.get('ruolo', '') or ''),
        str(p.get('azienda', '') or ''),
        str(p.get('sommario', '') or ''),
    ])).lower()

    if not testo.strip() and not p.get('nome') and not p.get('cognome'):
        return False, "Profilo vuoto o senza dati"

    # 1. Keyword negative → scarto immediato
    kw_neg = [k.strip().lower() for k in (imp.get('keyword_negative', '') or '').split(',') if k.strip()]
    for kw in kw_neg:
        if kw in testo:
            return False, f"Keyword negativa: «{kw}»"

    # 2. Almeno un termine positivo (ruoli, settori/istituti, keyword pos) deve matchare
    ruoli    = [r.strip().lower() for r in (imp.get('ruoli_target', '') or '').split(',') if r.strip()]
    settori  = [s.strip().lower() for s in (imp.get('settori', '') or '').split(',') if s.strip()]
    istituti = [i.strip().lower() for i in (imp.get('istituti', '') or '').split(',') if i.strip()]
    kw_pos   = [k.strip().lower() for k in (imp.get('keyword_positive', '') or '').split(',') if k.strip()]

    positivi = ruoli + settori + istituti + kw_pos
    if positivi and testo:
        if not any(term in testo for term in positivi):
            return False, "Nessun ruolo/settore target rilevato nel profilo"

    return True, ""


def normalizza_profilo(p):
    """
    Estrae i campi utili da un profilo restituito dall'actor Apify.
    Usa _str() per garantire che tutti i valori siano stringhe,
    anche quando Apify restituisce oggetti annidati.
    """
    nome    = _str(p.get("firstName") or p.get("first_name") or "")
    cognome = _str(p.get("lastName")  or p.get("last_name")  or "")
    ruolo   = _str(p.get("headline") or p.get("title") or p.get("occupation") or "")

    # Azienda corrente: può essere in una lista di posizioni
    azienda = ""
    posizione_corrente = p.get("currentPositions") or p.get("positions") or []
    if posizione_corrente and isinstance(posizione_corrente, list):
        prima = posizione_corrente[0] if isinstance(posizione_corrente[0], dict) else {}
        azienda = _str(prima.get("companyName") or prima.get("company") or "")
        if not ruolo:
            ruolo = _str(prima.get("title") or "")

    # Fallback azienda da campo diretto
    if not azienda:
        azienda = _str(p.get("companyName") or p.get("company") or "")

    # location può essere {"linkedinText": "Milan, Italy"} o stringa diretta
    location = _str(p.get("location") or p.get("geoLocation") or "")
    linkedin  = _str(p.get("linkedinUrl") or p.get("profileUrl") or p.get("url") or "")
    summary_raw = p.get("summary") or p.get("about") or ""
    summary   = _str(summary_raw)[:200]

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
    cronologia = db.execute(
        "SELECT * FROM ricerche_automatiche ORDER BY data_ricerca DESC"
    ).fetchall()
    db.close()
    cronologia = [dict(r) for r in cronologia]
    return render_template("ricerca.html",
                           imp_a_configurato=imp_a is not None,
                           imp_b_configurato=imp_b is not None,
                           cronologia=cronologia)


@ricerca_bp.route("/ricerca/cerca", methods=["POST"])
def cerca():
    """
    Esegue la ricerca su Apify, salva nella cronologia e persistela in profili_ricerca.
    Ogni profilo trovato viene salvato permanentemente con il testo completo.
    """
    dati = request.get_json()
    ruolo         = dati.get("ruolo", "").strip()
    citta         = dati.get("citta", "").strip()
    paese         = dati.get("paese", "").strip()
    azienda       = dati.get("azienda", "").strip()
    parole_chiave = dati.get("parole_chiave", "").strip()
    num_pagine    = int(dati.get("num_pagine", 1))
    tipo_profilo  = dati.get("tipo_profilo", "A")

    if not ruolo and not parole_chiave:
        return jsonify({"errore": "Inserisci almeno il ruolo o delle parole chiave"}), 400

    # Timeout wall-clock garantito: Apify a volte blocca la connessione SSL
    # senza rispondere, bypassando il timeout di requests. concurrent.futures
    # impone un limite assoluto di 150s indipendentemente dal comportamento del socket.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
        _fut = _pool.submit(cerca_apify, ruolo, citta, paese, azienda, parole_chiave, num_pagine)
        try:
            items, errore = _fut.result(timeout=150)
        except concurrent.futures.TimeoutError:
            return jsonify({"errore": "La ricerca ha impiegato troppo tempo. Prova con meno pagine o criteri più specifici."}), 408

    if errore:
        return jsonify({"errore": errore}), 500

    persone = [normalizza_profilo(p) for p in items if isinstance(p, dict)]

    # Salva la ricerca nella cronologia
    parametri_str = json.dumps({
        'ruolo': ruolo, 'citta': citta, 'azienda': azienda,
        'parole_chiave': parole_chiave,
    }, ensure_ascii=False)
    db = get_db()
    cur = db.execute(
        """INSERT INTO ricerche_automatiche
           (tipo_profilo, parametri, profili_trovati, profili_importati, fonte, stato)
           VALUES (?, ?, ?, 0, 'manuale', 'completata')""",
        (tipo_profilo, parametri_str, len(persone))
    )
    ricerca_id = cur.lastrowid

    # Salva ogni profilo trovato in profili_ricerca con il testo completo
    for p in persone:
        testo = _costruisci_testo_profilo(p)
        cur_p = db.execute(
            """INSERT INTO profili_ricerca
               (ricerca_id, nome, cognome, ruolo, azienda, location, linkedin_url, testo_profilo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ricerca_id, p["nome"], p["cognome"], p["ruolo"], p["azienda"],
             p["location"], p["linkedin"], testo)
        )
        p["profilo_ricerca_id"] = cur_p.lastrowid

    db.commit()
    db.close()

    return jsonify({
        "persone":    persone,
        "totale":     len(persone),
        "ricerca_id": ricerca_id,
    })


def _esegui_ricerca_background(job_id, tipo_profilo, max_profili, imp):
    """Thread daemon: esegue la ricerca Apify + analisi AI in background."""
    import logging
    log = logging.getLogger(__name__)
    db = get_db()

    def aggiorna(status=None, step=None, pct=None):
        sets, vals = [], []
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if step is not None:
            sets.append("step=?"); vals.append(step)
        if pct is not None:
            sets.append("percentuale=?"); vals.append(pct)
        vals.append(job_id)
        db.execute("UPDATE job_ricerche SET " + ", ".join(sets) + " WHERE job_id=?", vals)
        db.commit()

    try:
        aggiorna(status='in_corso', step='Connessione ad Apify...', pct=10)

        ruoli_raw        = imp.get("ruoli_target", "") or ""
        ruoli            = [r.strip() for r in ruoli_raw.split(",") if r.strip()]
        kw_positive      = imp.get("keyword_positive", "") or ""
        extra_settore    = (imp.get("settori", "") if tipo_profilo == "A" else imp.get("istituti", "")) or ""
        kw_parts         = [k.strip() for k in kw_positive.split(",") if k.strip()]
        kw_parts        += [s.strip() for s in extra_settore.split(",") if s.strip()]
        keywords         = " ".join(kw_parts[:6])
        ruolo_principale = ruoli[0] if ruoli else ""

        # Richiedi il doppio dei profili necessari per compensare filtri e duplicati
        num_pagine = max(1, (max_profili * 2 + 9) // 10)

        parametri_str = json.dumps({
            'ruolo': ruolo_principale, 'ruoli_tutti': ruoli_raw,
            'keywords': keywords, 'max_profili': max_profili,
            'location': 'Italy',
        }, ensure_ascii=False)

        aggiorna(step='Ricerca profili su LinkedIn (Italy)...', pct=25)
        items, errore = cerca_apify(
            ruolo_principale, "", "", "", keywords, num_pagine,
            ruoli_lista=ruoli, forza_italia=True
        )

        if errore:
            db.execute(
                "INSERT INTO ricerche_automatiche (tipo_profilo, parametri, profili_trovati, profili_importati, stato) VALUES (?, ?, 0, 0, 'errore')",
                (tipo_profilo, parametri_str)
            )
            db.commit()
            aggiorna(status='errore', step=errore)
            return

        trovati_apify     = len(items)
        scartati_qualita  = 0    # profili vuoti/non italiani/incompleti
        scartati_filtro   = 0    # non superano il filtro keyword locale
        gia_presenti      = 0    # già in database
        importati         = 0
        valutati          = 0
        punteggi: list    = []
        motivi_qualita: dict = {}
        motivi_filtro:  dict = {}

        aggiorna(step=f'{trovati_apify} profili trovati da Apify. Filtraggio in corso...', pct=50)

        # ── Pipeline di filtraggio ─────────────────────────────────────────────
        # 1. Qualità (profili vuoti / non italiani)
        # 2. Filtro locale (keyword matching con impostazioni)
        # 3. Deduplicazione contro candidati già presenti
        items_da_importare = []
        for item in items:
            p = normalizza_profilo(item)

            # Filtro qualità
            ok_q, motivo_q = _filtro_qualita(p)
            if not ok_q:
                scartati_qualita += 1
                motivi_qualita[motivo_q] = motivi_qualita.get(motivo_q, 0) + 1
                continue

            # Filtro locale (ruoli, settori, keyword)
            ok_l, motivo_l = _filtro_locale(p, imp)
            if not ok_l:
                scartati_filtro += 1
                motivi_filtro[motivo_l] = motivi_filtro.get(motivo_l, 0) + 1
                continue

            # Deduplicazione
            if _controlla_duplicato(db, p):
                gia_presenti += 1
                continue

            items_da_importare.append(p)
            if len(items_da_importare) >= max_profili:
                break

        trovati_filtrati = len(items_da_importare)
        aggiorna(step=f'Filtraggio completato. Importazione {trovati_filtrati} candidati...', pct=70)

        cur_r = db.execute(
            "INSERT INTO ricerche_automatiche (tipo_profilo, parametri, profili_trovati, fonte, stato) VALUES (?, ?, ?, 'apify', 'in_corso')",
            (tipo_profilo, parametri_str, trovati_apify)
        )
        ricerca_id = cur_r.lastrowid
        db.commit()

        for p in items_da_importare:
            testo = _costruisci_testo_profilo(p)
            _gestore = "Salvatore Sabia" if tipo_profilo == "A" else ("Firdaous Filahi" if tipo_profilo == "B" else "Non assegnato")
            cur = db.execute(
                "INSERT INTO candidati (nome, cognome, ruolo_attuale, azienda, profilo_linkedin, tipo_profilo, stato, note, ricerca_id, gestore) VALUES (?, ?, ?, ?, ?, ?, 'Da valutare', ?, ?, ?)",
                (p["nome"], p["cognome"], p["ruolo"], p["azienda"], p["linkedin"], tipo_profilo, p["headline"], ricerca_id, _gestore)
            )
            db.commit()
            candidato_id = cur.lastrowid
            importati += 1

            db.execute(
                "INSERT INTO profili_ricerca (ricerca_id, nome, cognome, ruolo, azienda, location, linkedin_url, testo_profilo, candidato_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ricerca_id, p["nome"], p["cognome"], p["ruolo"], p["azienda"], p["location"], p["linkedin"], testo, candidato_id)
            )
            db.commit()

            if valutati < 10:
                _ai_total = min(len(items_da_importare), 10)
                _ai_pct   = 85 + int((valutati / max(1, _ai_total)) * 10)
                aggiorna(step=f'Analisi AI candidato {valutati + 1}/{_ai_total}...', pct=_ai_pct)
                try:
                    risultato     = analizza_profilo_linkedin(testo, tipo_profilo, imp)
                    punteggio     = int(risultato.get("punteggio") or 0) or None
                    spunti_raw    = risultato.get("spunti_contatto", [])
                    spunti_json   = json.dumps(spunti_raw if isinstance(spunti_raw, list) else [], ensure_ascii=False)
                    analisi_str   = str(risultato.get("analisi_percorso") or "")
                    messaggio_str = str(risultato.get("messaggio_outreach") or "")
                    db.execute(
                        "UPDATE candidati SET punteggio=?, analisi=?, spunti=?, messaggio_outreach=?, stato='Da contattare', data_aggiornamento=CURRENT_TIMESTAMP WHERE id=?",
                        (punteggio, analisi_str, spunti_json, messaggio_str, candidato_id)
                    )
                    nome_completo = f"{p['nome']} {p['cognome']}".strip() or None
                    anteprima     = f"{p['nome']} {p['cognome']} — {p['ruolo']}".strip()[:120]
                    db.execute(
                        "INSERT INTO valutazioni (nome_contatto, ruolo_attuale, azienda, tipo_profilo, anteprima_testo, punteggio, analisi, spunti, messaggio_outreach, candidato_id, fonte) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (nome_completo, p['ruolo'] or None, p['azienda'] or None, tipo_profilo, anteprima, punteggio, analisi_str, spunti_json, messaggio_str, candidato_id, 'ricerca_automatica')
                    )
                    db.commit()
                    valutati += 1
                    if punteggio:
                        punteggi.append(punteggio)
                except Exception:
                    log.exception("Errore analisi AI per %s %s", p.get('nome'), p.get('cognome'))

        punteggio_medio = round(sum(punteggi) / len(punteggi), 1) if punteggi else None
        db.execute(
            "UPDATE ricerche_automatiche SET profili_importati=?, punteggio_medio=?, stato='completata' WHERE id=?",
            (importati, punteggio_medio, ricerca_id)
        )
        db.commit()

        risultati_json = json.dumps({
            # Contatori separati per trasparenza
            "trovati_apify":    trovati_apify,
            "filtrati":         trovati_filtrati,
            "gia_presenti":     gia_presenti,
            "importati":        importati,
            "valutati":         valutati,
            "punteggio_medio":  punteggio_medio,
            # Dettaglio motivi scarto
            "scartati_qualita": scartati_qualita,
            "scartati_filtro":  scartati_filtro,
            "motivi_qualita":   motivi_qualita,
            "motivi_filtro":    motivi_filtro,
        }, ensure_ascii=False)

        db.execute(
            "UPDATE job_ricerche SET status='completato', step='Ricerca completata!', risultati=?, percentuale=100, data_fine=CURRENT_TIMESTAMP WHERE job_id=?",
            (risultati_json, job_id)
        )
        db.commit()

    except Exception as e:
        log.exception("Errore background job=%s", job_id)
        try:
            db.execute(
                "UPDATE job_ricerche SET status='errore', errore=?, step=?, data_fine=CURRENT_TIMESTAMP WHERE job_id=?",
                (str(e), f"Errore: {str(e)[:200]}", job_id)
            )
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


@ricerca_bp.route("/ricerca/automatica", methods=["POST"])
def automatica():
    """Avvia la ricerca automatica in background e restituisce subito un job_id."""
    dati         = request.get_json()
    tipo_profilo = dati.get("tipo_profilo", "A")
    max_profili  = max(1, min(int(dati.get("max_profili", 20)), 100))

    db = get_db()
    imp_row = db.execute(
        "SELECT * FROM impostazioni_profilo WHERE profilo = ?", (tipo_profilo,)
    ).fetchone()
    db.close()

    if not imp_row:
        return jsonify({"errore": f"Impostazioni Profilo {tipo_profilo} non configurate. "
                                  f"Vai in Impostazioni e salva i parametri."}), 400

    imp    = dict(imp_row)
    job_id = str(uuid.uuid4())

    db2 = get_db()
    db2.execute(
        "INSERT INTO job_ricerche (job_id, tipo_profilo, status, step) VALUES (?, ?, 'avviato', ?)",
        (job_id, tipo_profilo, 'Preparazione ricerca...')
    )
    db2.commit()
    db2.close()

    t = threading.Thread(
        target=_esegui_ricerca_background,
        args=(job_id, tipo_profilo, max_profili, imp),
        daemon=True
    )
    t.start()

    return jsonify({"job_id": job_id, "status": "avviato"})


@ricerca_bp.route("/ricerca/stato/<job_id>")
def stato_job(job_id):
    """Restituisce lo stato attuale di un job di ricerca."""
    db  = get_db()
    row = db.execute("SELECT * FROM job_ricerche WHERE job_id = ?", (job_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({"errore": "Job non trovato"}), 404
    row = dict(row)
    if row.get("risultati"):
        try:
            row["risultati"] = json.loads(row["risultati"])
        except Exception:
            pass
    return jsonify(row)


@ricerca_bp.route("/ricerca/export_csv")
def export_csv():
    """Esporta la cronologia ricerche automatiche in formato CSV."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM ricerche_automatiche ORDER BY data_ricerca DESC"
    ).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', 'Data', 'Tipo Profilo', 'Profili Trovati',
        'Importati', 'Punteggio Medio', 'Stato', 'Parametri'
    ])
    for r in rows:
        writer.writerow([
            r['id'],
            r['data_ricerca'],
            r['tipo_profilo'],
            r['profili_trovati'],
            r['profili_importati'],
            r['punteggio_medio'] if r['punteggio_medio'] else '',
            r['stato'],
            r['parametri'] or '',
        ])

    return Response(
        '\ufeff' + output.getvalue(),  # BOM per compatibilità Excel
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=cronologia_ricerche.csv'}
    )


@ricerca_bp.route("/ricerca/analizza_candidato", methods=["POST"])
def analizza_candidato():
    """
    Esegue analisi AI su un candidato. Gestisce tre casi:
    1. candidato_id → candidato già in pipeline (re-analisi o prima analisi)
    2. profilo_ricerca_id → profilo salvato in profili_ricerca ma non ancora in pipeline
    3. dati testuali diretti → candidato completamente nuovo
    Salva automaticamente in candidati (pipeline) e valutazioni (cronologia).
    """
    dati = request.get_json()
    candidato_id       = dati.get("candidato_id")
    profilo_ricerca_id = dati.get("profilo_ricerca_id")
    tipo_profilo       = dati.get("tipo_profilo", "A")
    ricerca_id         = dati.get("ricerca_id")

    db = get_db()

    if candidato_id:
        # Caso 1: candidato già in DB (pipeline)
        c = db.execute(
            "SELECT * FROM candidati WHERE id = ?", (candidato_id,)
        ).fetchone()
        if not c:
            db.close()
            return jsonify({"errore": "Candidato non trovato"}), 404
        tipo_profilo  = c["tipo_profilo"]
        ricerca_id    = c["ricerca_id"]
        # Cerca il testo profilo in profili_ricerca se disponibile
        pr = db.execute(
            "SELECT testo_profilo FROM profili_ricerca WHERE candidato_id = ? LIMIT 1",
            (candidato_id,)
        ).fetchone()
        if pr and pr.get("testo_profilo"):
            testo_profilo = pr["testo_profilo"]
        else:
            testo_profilo = (
                f"Nome: {c['nome']} {c['cognome']}\n"
                f"Ruolo: {c['ruolo_attuale'] or ''}\n"
                f"Azienda: {c['azienda'] or ''}\n"
            )
            if c.get("profilo_linkedin"):
                testo_profilo += f"LinkedIn: {c['profilo_linkedin']}\n"
        nome    = c["nome"]
        cognome = c["cognome"]
        ruolo   = c["ruolo_attuale"] or ""
        azienda = c["azienda"] or ""
        linkedin = c.get("profilo_linkedin") or ""

    elif profilo_ricerca_id:
        # Caso 2: profilo già in profili_ricerca ma non ancora in pipeline
        pr = db.execute(
            "SELECT * FROM profili_ricerca WHERE id = ?", (profilo_ricerca_id,)
        ).fetchone()
        if not pr:
            db.close()
            return jsonify({"errore": "Profilo non trovato"}), 404
        testo_profilo = pr["testo_profilo"] or ""
        nome          = pr["nome"] or ""
        cognome       = pr["cognome"] or ""
        ruolo         = pr["ruolo"] or ""
        azienda       = pr["azienda"] or ""
        linkedin      = pr["linkedin_url"] or ""
        ricerca_id    = pr["ricerca_id"]

    else:
        # Caso 3: dati testuali diretti (ricerca.html, vecchio flusso)
        testo_profilo = dati.get("testo_profilo", "").strip()
        nome    = dati.get("nome", "").strip()
        cognome = dati.get("cognome", "").strip()
        ruolo   = dati.get("ruolo", "").strip()
        azienda = dati.get("azienda", "").strip()
        linkedin = dati.get("linkedin", "").strip()

    if not testo_profilo:
        db.close()
        return jsonify({"errore": "Testo profilo mancante"}), 400

    # Carica impostazioni per il tipo profilo selezionato
    imp_row = db.execute(
        "SELECT * FROM impostazioni_profilo WHERE profilo = ?", (tipo_profilo,)
    ).fetchone()
    imp = dict(imp_row) if imp_row else None

    try:
        risultato = analizza_profilo_linkedin(testo_profilo, tipo_profilo, imp)
    except Exception as e:
        db.close()
        return jsonify({"errore": str(e)}), 500

    # Coercion tipi: ogni valore dal risultato AI deve essere del tipo giusto per PostgreSQL
    def _s(v, fallback=None):
        """Stringa o None."""
        if v in (None, "", {}, []):
            return fallback
        return str(v) if not isinstance(v, str) else (v or fallback)
    def _i(v):
        """Intero o None."""
        try: return int(v) if v not in (None, "", {}, []) else None
        except (TypeError, ValueError): return None

    punteggio     = _i(risultato.get("punteggio"))
    nome_contatto = _s(risultato.get("nome_contatto"), f"{nome} {cognome}".strip() or None)
    ruolo_ai      = _s(risultato.get("ruolo_attuale"), ruolo or None)
    azienda_ai    = _s(risultato.get("azienda"), azienda or None)
    spunti_raw    = risultato.get("spunti_contatto", [])
    spunti_json   = json.dumps(spunti_raw if isinstance(spunti_raw, list) else [], ensure_ascii=False)
    analisi_str   = _s(risultato.get("analisi_percorso"), "") or ""
    messaggio_str = _s(risultato.get("messaggio_outreach"), "") or ""
    anteprima     = testo_profilo[:120].replace("\n", " ").strip()

    e_candidato_nuovo = not candidato_id  # True se stiamo creando un nuovo record

    if candidato_id:
        # Aggiorna candidato esistente con analisi e stato pipeline
        db.execute(
            """UPDATE candidati SET
               punteggio=?, analisi=?, spunti=?, messaggio_outreach=?,
               stato='Da contattare', data_aggiornamento=CURRENT_TIMESTAMP
               WHERE id=?""",
            (punteggio, analisi_str, spunti_json, messaggio_str, candidato_id)
        )
    else:
        # Crea nuovo candidato direttamente in pipeline come "Da contattare"
        _gestore = "Salvatore Sabia" if tipo_profilo == "A" else ("Firdaous Filahi" if tipo_profilo == "B" else "Non assegnato")
        cur = db.execute(
            """INSERT INTO candidati
               (nome, cognome, ruolo_attuale, azienda, profilo_linkedin,
                tipo_profilo, stato, punteggio, analisi, spunti,
                messaggio_outreach, ricerca_id, gestore)
               VALUES (?, ?, ?, ?, ?, ?, 'Da contattare', ?, ?, ?, ?, ?, ?)""",
            (nome, cognome, ruolo_ai, azienda_ai, linkedin,
             tipo_profilo, punteggio, analisi_str,
             spunti_json, messaggio_str, ricerca_id, _gestore)
        )
        candidato_id = cur.lastrowid

    # Fonte nella cronologia: "ricerca_[id]" se viene da una ricerca, "ricerca_manuale" altrimenti
    fonte = f"ricerca_{ricerca_id}" if ricerca_id else "ricerca_manuale"

    # Salva sempre nella cronologia valutazioni
    db.execute(
        """INSERT INTO valutazioni
           (nome_contatto, ruolo_attuale, azienda, tipo_profilo,
            anteprima_testo, punteggio, analisi, spunti, messaggio_outreach,
            candidato_id, fonte)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nome_contatto, ruolo_ai, azienda_ai, tipo_profilo, anteprima,
         punteggio, analisi_str, spunti_json, messaggio_str, candidato_id, fonte)
    )

    # Incrementa profili_importati solo per nuovi candidati, non per ri-analisi
    if ricerca_id and e_candidato_nuovo:
        db.execute(
            """UPDATE ricerche_automatiche
               SET profili_importati = COALESCE(profili_importati, 0) + 1
               WHERE id = ?""",
            (ricerca_id,)
        )

    # Collega profili_ricerca al candidato appena creato/aggiornato
    if profilo_ricerca_id:
        db.execute(
            "UPDATE profili_ricerca SET candidato_id = ? WHERE id = ?",
            (candidato_id, profilo_ricerca_id)
        )
    elif ricerca_id and e_candidato_nuovo:
        # Per nuovi candidati senza profilo_ricerca_id, cerca per corrispondenza nome+ricerca
        db.execute(
            """UPDATE profili_ricerca SET candidato_id = ?
               WHERE ricerca_id = ? AND candidato_id IS NULL
               AND nome = ? AND cognome = ?""",
            (candidato_id, ricerca_id, nome, cognome)
        )

    db.commit()
    db.close()

    return jsonify({**risultato, "candidato_id": candidato_id})


@ricerca_bp.route("/ricerca/dettaglio/<int:ricerca_id>")
def dettaglio_ricerca(ricerca_id):
    """
    Pagina di dettaglio di una ricerca.
    Mostra tutti i profili trovati (da profili_ricerca) con i dati di analisi e pipeline.
    Fallback sui candidati diretti per ricerche precedenti all'introduzione di profili_ricerca.
    """
    db = get_db()
    ricerca = db.execute(
        "SELECT * FROM ricerche_automatiche WHERE id = ?", (ricerca_id,)
    ).fetchone()

    if not ricerca:
        db.close()
        return jsonify({"errore": "Ricerca non trovata"}), 404

    # Prima tenta con profili_ricerca (ricerche nuove)
    profili = db.execute(
        """SELECT pr.id           AS profilo_id,
                  pr.nome,        pr.cognome,
                  pr.ruolo,       pr.azienda,
                  pr.location,    pr.linkedin_url,
                  pr.testo_profilo,
                  pr.candidato_id,
                  c.punteggio,    c.analisi,
                  c.spunti,       c.messaggio_outreach,
                  c.stato
           FROM profili_ricerca pr
           LEFT JOIN candidati c ON pr.candidato_id = c.id
           WHERE pr.ricerca_id = ?
           ORDER BY c.punteggio DESC NULLS LAST, pr.id""",
        (ricerca_id,)
    ).fetchall()

    usa_fallback = (len(profili) == 0)

    if usa_fallback:
        # Fallback: ricerche precedenti che hanno candidati ma non profili_ricerca
        profili = db.execute(
            """SELECT id            AS profilo_id,
                      id            AS candidato_id,
                      nome,         cognome,
                      ruolo_attuale AS ruolo,
                      azienda,
                      NULL          AS location,
                      profilo_linkedin AS linkedin_url,
                      NULL          AS testo_profilo,
                      punteggio,    analisi,
                      spunti,       messaggio_outreach,
                      stato
               FROM candidati
               WHERE ricerca_id = ?
               ORDER BY punteggio DESC NULLS LAST""",
            (ricerca_id,)
        ).fetchall()

    db.close()

    ricerca = dict(ricerca)
    profili  = [dict(p) for p in profili]

    try:
        parametri = json.loads(ricerca.get('parametri') or '{}')
    except Exception:
        parametri = {}

    return render_template("ricerca_dettaglio.html",
                           ricerca=ricerca,
                           profili=profili,
                           parametri=parametri,
                           usa_fallback=usa_fallback)


@ricerca_bp.route("/ricerca/dettaglio/<int:ricerca_id>/export_csv")
def export_csv_candidati(ricerca_id):
    """Esporta in CSV tutti i profili di una ricerca specifica."""
    db = get_db()
    ricerca = db.execute(
        "SELECT tipo_profilo, data_ricerca FROM ricerche_automatiche WHERE id = ?",
        (ricerca_id,)
    ).fetchone()
    # Prova prima profili_ricerca, fallback su candidati
    righe = db.execute(
        """SELECT pr.nome, pr.cognome, pr.ruolo, pr.azienda,
                  c.punteggio, c.stato, c.data_aggiornamento
           FROM profili_ricerca pr
           LEFT JOIN candidati c ON pr.candidato_id = c.id
           WHERE pr.ricerca_id = ?
           ORDER BY c.punteggio DESC NULLS LAST, pr.id""",
        (ricerca_id,)
    ).fetchall()
    if not righe:
        righe = db.execute(
            """SELECT nome, cognome, ruolo_attuale AS ruolo, azienda,
                      punteggio, stato, data_aggiornamento
               FROM candidati WHERE ricerca_id = ? ORDER BY punteggio DESC NULLS LAST""",
            (ricerca_id,)
        ).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Nome', 'Cognome', 'Ruolo', 'Azienda', 'Punteggio', 'Stato', 'Data Valutazione'])
    for c in righe:
        writer.writerow([
            c['nome'], c['cognome'],
            c.get('ruolo') or '',
            c['azienda'] or '',
            c['punteggio'] or '',
            c['stato'] or '',
            c['data_aggiornamento'] or '',
        ])

    tipo = ricerca['tipo_profilo'] if ricerca else 'X'
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=candidati_ricerca_{ricerca_id}_profilo{tipo}.csv'}
    )


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

    _gestore = "Salvatore Sabia" if tipo_profilo == "A" else ("Firdaous Filahi" if tipo_profilo == "B" else "Non assegnato")
    db = get_db()
    cur = db.execute(
        """INSERT INTO candidati
           (nome, cognome, ruolo_attuale, azienda, profilo_linkedin, tipo_profilo, note, gestore)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (nome, cognome, ruolo_attuale, azienda, linkedin, tipo_profilo, note, _gestore),
    )
    db.commit()
    nuovo_id = cur.lastrowid
    db.close()

    return jsonify({"successo": True, "candidato_id": nuovo_id})
