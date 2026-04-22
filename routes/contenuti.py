"""
Modulo 4 — Creazione Contenuti LinkedIn.
Genera 3 varianti di post LinkedIn tramite Claude AI, con profilo voce autore.
"""

import urllib.parse
import base64
import time
import requests
from flask import Blueprint, render_template, request, jsonify
from database import get_db
from ai_helpers import genera_contenuti_linkedin, genera_prompt_immagine, analizza_profilo_voce
from routes.auth import get_org_id

# Blueprint per il modulo contenuti
contenuti_bp = Blueprint("contenuti", __name__)


@contenuti_bp.route("/contenuti")
def index():
    """Pagina principale del modulo creazione contenuti."""
    org_id = get_org_id()
    db = get_db()
    storico = db.execute(
        "SELECT * FROM contenuti_linkedin WHERE organizzazione_id = ? ORDER BY data_creazione DESC LIMIT 10",
        (org_id,)
    ).fetchall()
    profili_voce = db.execute(
        "SELECT * FROM profili_voce WHERE organizzazione_id = ? ORDER BY creato_il DESC",
        (org_id,)
    ).fetchall()
    db.close()
    return render_template(
        "contenuti.html",
        storico=[dict(s) for s in storico],
        profili_voce=[dict(p) for p in profili_voce],
    )


@contenuti_bp.route("/contenuti/analizza-profilo", methods=["POST"])
def analizza_profilo():
    """
    Riceve nome + URL LinkedIn, chiama EnrichLayer, analizza con Claude
    e salva il profilo voce in DB.
    """
    dati         = request.get_json() or {}
    nome         = (dati.get("nome") or "").strip()
    linkedin_url = (dati.get("linkedin_url") or "").strip()

    if not nome:
        return jsonify({"errore": "Il nome è obbligatorio"}), 400

    analisi = {"tono_prevalente": "", "settore": "", "bio_breve": ""}

    if linkedin_url and "linkedin.com/in/" in linkedin_url:
        try:
            from proxycurl_helpers import arricchisci_profilo
            dati_prx = arricchisci_profilo(linkedin_url)
            if dati_prx:
                analisi = analizza_profilo_voce(dati_prx, nome)
        except Exception as e:
            # Non blocca: salva il profilo senza analisi
            import logging
            logging.getLogger(__name__).warning("analizza_profilo_voce failed: %s", e)

    org_id = get_org_id()
    db = get_db()
    cur = db.execute(
        """INSERT INTO profili_voce (nome, linkedin_url, settore, tono_prevalente, bio_breve, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            nome,
            linkedin_url,
            analisi.get("settore", ""),
            analisi.get("tono_prevalente", ""),
            analisi.get("bio_breve", ""),
            org_id,
        ),
    )
    db.commit()
    profilo_id = cur.lastrowid
    profilo_row = db.execute("SELECT * FROM profili_voce WHERE id = ?", (profilo_id,)).fetchone()
    db.close()

    return jsonify({"ok": True, "profilo": dict(profilo_row)})


@contenuti_bp.route("/contenuti/profilo/<int:pid>", methods=["DELETE"])
def elimina_profilo(pid):
    org_id = get_org_id()
    db = get_db()
    db.execute("DELETE FROM profili_voce WHERE id = ? AND organizzazione_id = ?", (pid, org_id))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@contenuti_bp.route("/contenuti/genera", methods=["POST"])
def genera():
    """Endpoint AJAX per generare i post LinkedIn."""
    dati           = request.get_json() or {}
    tema           = (dati.get("tema") or "").strip()
    obiettivo      = (dati.get("obiettivo") or "insight").strip()
    contesto       = (dati.get("contesto") or "").strip()
    profilo_voce_id = dati.get("profilo_voce_id")

    if not tema:
        return jsonify({"errore": "Inserire il tema del post"}), 400

    # Carica il profilo voce se specificato
    org_id = get_org_id()
    profilo_voce = {}
    if profilo_voce_id:
        db = get_db()
        row = db.execute(
            "SELECT * FROM profili_voce WHERE id = ? AND organizzazione_id = ?",
            (profilo_voce_id, org_id)
        ).fetchone()
        db.close()
        if row:
            profilo_voce = dict(row)

    # Genera le 3 varianti con Claude
    risultato = genera_contenuti_linkedin(tema, obiettivo, contesto, profilo_voce)

    # Salva nel database
    db = get_db()
    db.execute(
        """INSERT INTO contenuti_linkedin
           (tema, tono, profilo_destinazione, variante_1, variante_2, variante_3,
            obiettivo, contesto, profilo_voce_id, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tema,
            obiettivo,
            profilo_voce.get("nome", ""),
            risultato.get("variante_1", ""),
            risultato.get("variante_2", ""),
            risultato.get("variante_3", ""),
            obiettivo,
            contesto,
            profilo_voce_id,
            org_id,
        ),
    )
    db.commit()
    db.close()

    # Aggiungi info profilo alla risposta per l'anteprima LinkedIn
    risultato["profilo_nome"]  = profilo_voce.get("nome", "")
    risultato["profilo_bio"]   = profilo_voce.get("bio_breve", "")
    risultato["profilo_settore"] = profilo_voce.get("settore", "")

    return jsonify(risultato)


@contenuti_bp.route("/contenuti/genera_immagine", methods=["POST"])
def genera_immagine():
    """
    Genera un'immagine per il post LinkedIn usando Pollinations.ai (gratuito, no API key).
    Claude costruisce il prompt ottimizzato, Pollinations genera l'immagine con FLUX.
    """
    dati          = request.get_json() or {}
    testo_post    = (dati.get("testo_post") or "").strip()
    tema          = (dati.get("tema") or "").strip()
    obiettivo     = (dati.get("obiettivo") or "")
    prompt_custom = (dati.get("prompt_custom") or "").strip()

    if not testo_post:
        return jsonify({"errore": "Testo post mancante"}), 400

    # Claude genera il prompt ottimizzato per FLUX
    prompt_img = genera_prompt_immagine(testo_post, tema, obiettivo, prompt_custom)

    # Scarica l'immagine dal backend
    prompt_encoded = urllib.parse.quote(prompt_img)
    seed = abs(hash(prompt_img + prompt_custom)) % 99999
    url_pollinations = (
        f"https://image.pollinations.ai/prompt/{prompt_encoded}"
        f"?width=1200&height=628&model=turbo&seed={seed}"
    )
    headers = {"User-Agent": "Mozilla/5.0"}

    for tentativo in range(3):
        try:
            resp_img = requests.get(url_pollinations, timeout=90, headers=headers)
            if resp_img.status_code == 429:
                time.sleep(5)
                continue
            resp_img.raise_for_status()
            if resp_img.content[:4] in (b"<htm", b"<!do", b'{"er'):
                return jsonify({"errore": "Il servizio immagini non è disponibile al momento. Riprova."}), 500
            img_b64 = base64.b64encode(resp_img.content).decode("utf-8")
            content_type = resp_img.headers.get("Content-Type", "image/jpeg")
            data_url = f"data:{content_type};base64,{img_b64}"
            return jsonify({"url": data_url, "prompt": prompt_img})
        except requests.exceptions.RequestException as e:
            if tentativo == 2:
                return jsonify({"errore": f"Errore: {str(e)}"}), 500
            time.sleep(3)

    return jsonify({"errore": "Servizio temporaneamente non disponibile. Riprova tra qualche secondo."}), 500
