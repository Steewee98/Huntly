"""
Modulo Analisi Profilo Personale LinkedIn.
Estrae dati del profilo tramite EnrichLayer, li analizza con Claude
e fornisce suggerimenti concreti di personal branding.
"""

import json
import logging
from flask import Blueprint, render_template, request, jsonify
from database import get_db
from ai_helpers import analizza_profilo_personale
from routes.auth import get_org_id

log = logging.getLogger(__name__)

profilo_personale_bp = Blueprint("profilo_personale", __name__)


def _estrai_testo_profilo_completo(dati_prx: dict) -> str:
    """
    Estrae headline, summary, esperienze, education e skills da un profilo Proxycurl
    formattando il tutto come testo leggibile per Claude.
    """
    if not dati_prx:
        return ""
    parti = []

    nome = " ".join(filter(None, [dati_prx.get("first_name"), dati_prx.get("last_name")]))
    if nome:
        parti.append(f"Nome: {nome}")

    headline = dati_prx.get("headline") or dati_prx.get("title") or ""
    if headline:
        parti.append(f"Headline: {headline}")

    location = dati_prx.get("city") or dati_prx.get("country") or dati_prx.get("location") or ""
    if location:
        parti.append(f"Location: {location}")

    follower = dati_prx.get("follower_count")
    connections = dati_prx.get("connections")
    if follower:
        parti.append(f"Follower: {follower:,}")
    if connections:
        parti.append(f"Connessioni: {connections}")

    summary = dati_prx.get("summary") or dati_prx.get("about") or ""
    if summary:
        parti.append(f"\nAbout/Summary:\n{summary[:800]}")

    # Esperienze
    experiences = dati_prx.get("experiences") or dati_prx.get("experience") or []
    if experiences:
        parti.append("\nEsperienze professionali:")
        for exp in experiences[:5]:
            if not isinstance(exp, dict):
                continue
            titolo = exp.get("title") or exp.get("position") or ""
            azienda = exp.get("company") or exp.get("company_name") or ""
            desc = exp.get("description") or ""
            riga = f"  • {titolo}"
            if azienda:
                riga += f" @ {azienda}"
            if desc:
                riga += f": {desc[:120]}"
            parti.append(riga)

    # Education
    education = dati_prx.get("education") or []
    if education:
        parti.append("\nFormazione:")
        for edu in education[:3]:
            if not isinstance(edu, dict):
                continue
            scuola = edu.get("school") or edu.get("institution") or ""
            grado  = edu.get("degree_name") or edu.get("field_of_study") or ""
            if scuola or grado:
                parti.append(f"  • {grado} {scuola}".strip())

    # Skills
    skills = dati_prx.get("skills") or []
    if skills:
        if isinstance(skills[0], dict):
            nomi = [s.get("name", "") for s in skills[:15] if s.get("name")]
        else:
            nomi = [str(s) for s in skills[:15]]
        if nomi:
            parti.append(f"\nSkill: {', '.join(nomi)}")

    # Certificazioni
    certs = dati_prx.get("certifications") or []
    if certs:
        nomi_c = [c.get("name", "") for c in certs[:5] if isinstance(c, dict) and c.get("name")]
        if nomi_c:
            parti.append(f"Certificazioni: {', '.join(nomi_c)}")

    # Raccomandazioni
    recs = dati_prx.get("recommendations") or []
    if recs:
        parti.append(f"Raccomandazioni ricevute: {len(recs)}")

    # Attività/post recenti
    activities = dati_prx.get("activities") or []
    if activities:
        titoli = [a.get("title", "") for a in activities[:3] if isinstance(a, dict) and a.get("title")]
        if titoli:
            parti.append("\nUltimi post LinkedIn:\n" + "\n".join(f"  • {t[:100]}" for t in titoli))

    return "\n".join(parti)


@profilo_personale_bp.route("/profilo-personale")
def index():
    """Pagina analisi profilo personale."""
    org_id = get_org_id()
    db = get_db()
    storico = db.execute(
        "SELECT id, linkedin_url, punteggio, creato_il FROM analisi_profilo WHERE organizzazione_id = ? ORDER BY creato_il DESC LIMIT 5",
        (org_id,)
    ).fetchall()
    db.close()
    return render_template("profilo_personale.html", storico=[dict(r) for r in storico])


@profilo_personale_bp.route("/profilo-personale/analizza", methods=["POST"])
def analizza():
    """
    Analizza il profilo LinkedIn.
    Tenta prima EnrichLayer; se fallisce usa testo_manuale se fornito.
    """
    dati         = request.get_json() or {}
    linkedin_url = (dati.get("linkedin_url") or "").strip()
    testo_manuale = (dati.get("testo_manuale") or "").strip()

    if not linkedin_url and not testo_manuale:
        return jsonify({"errore": "Inserisci l'URL LinkedIn o incolla il testo del profilo."}), 400

    testo_profilo = ""
    usato_enrichlayer = False

    # Tenta EnrichLayer se URL fornito
    if linkedin_url and "linkedin.com/in/" in linkedin_url:
        try:
            from proxycurl_helpers import arricchisci_profilo
            dati_prx = arricchisci_profilo(linkedin_url)
            if dati_prx:
                testo_profilo = _estrai_testo_profilo_completo(dati_prx)
                usato_enrichlayer = True
        except Exception as e:
            log.warning("EnrichLayer fallito per profilo personale: %s", e)

    # Fallback: testo manuale
    if not testo_profilo:
        if testo_manuale:
            testo_profilo = testo_manuale
        else:
            return jsonify({
                "errore": "non_disponibile",
                "messaggio": "EnrichLayer non ha restituito dati. Incolla manualmente il testo del profilo."
            }), 422

    # Analisi Claude
    try:
        risultato = analizza_profilo_personale(testo_profilo)
    except Exception as e:
        log.exception("analizza_profilo_personale fallita")
        return jsonify({"errore": f"Errore analisi AI: {str(e)}"}), 500

    # Salva in DB
    org_id = get_org_id()
    db = get_db()
    cur = db.execute(
        """INSERT INTO analisi_profilo
           (linkedin_url, punteggio, headline_attuale, headline_suggerita,
            about_attuale, about_suggerito, punti_forza, aree_miglioramento,
            keyword_mancanti, dati_raw, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            linkedin_url,
            risultato.get("punteggio"),
            risultato.get("headline_attuale", ""),
            risultato.get("headline_suggerita", ""),
            risultato.get("about_attuale", ""),
            risultato.get("about_suggerito", ""),
            json.dumps(risultato.get("punti_forza", []), ensure_ascii=False),
            json.dumps(risultato.get("aree_miglioramento", []), ensure_ascii=False),
            json.dumps(risultato.get("keyword_mancanti", []), ensure_ascii=False),
            json.dumps(risultato, ensure_ascii=False),
            org_id,
        ),
    )
    db.commit()
    analisi_id = cur.lastrowid
    db.close()

    risultato["analisi_id"]       = analisi_id
    risultato["usato_enrichlayer"] = usato_enrichlayer
    return jsonify(risultato)


@profilo_personale_bp.route("/profilo-personale/salva-profilo-voce", methods=["POST"])
def salva_profilo_voce():
    """
    Salva i dati estratti dall'analisi nella tabella profili_voce
    per usarli nella sezione Contenuti LinkedIn.
    """
    dati = request.get_json() or {}
    nome         = (dati.get("nome") or "").strip()
    linkedin_url = (dati.get("linkedin_url") or "").strip()
    bio_breve    = (dati.get("bio_breve") or "").strip()
    tono         = (dati.get("tono_prevalente") or "").strip()
    settore      = (dati.get("settore") or "").strip()

    if not nome:
        return jsonify({"errore": "Il nome è obbligatorio."}), 400

    org_id = get_org_id()
    db = get_db()
    cur = db.execute(
        """INSERT INTO profili_voce (nome, linkedin_url, bio_breve, tono_prevalente, settore, organizzazione_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (nome, linkedin_url, bio_breve, tono, settore, org_id),
    )
    db.commit()
    profilo_id = cur.lastrowid
    db.close()

    return jsonify({"ok": True, "profilo_voce_id": profilo_id})


@profilo_personale_bp.route("/profilo-personale/<int:analisi_id>")
def dettaglio(analisi_id):
    """Carica un'analisi precedente."""
    org_id = get_org_id()
    db = get_db()
    row = db.execute(
        "SELECT * FROM analisi_profilo WHERE id = ? AND organizzazione_id = ?", (analisi_id, org_id)
    ).fetchone()
    db.close()
    if not row:
        return jsonify({"errore": "Analisi non trovata"}), 404
    r = dict(row)
    for campo in ("punti_forza", "aree_miglioramento", "keyword_mancanti", "dati_raw"):
        if r.get(campo):
            try:
                r[campo] = json.loads(r[campo])
            except Exception:
                pass
    return jsonify(r)
