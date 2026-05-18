"""
Modulo Analisi Profilo Personale LinkedIn.
Hub di personal branding: analisi profilo + contenuti, storico con trend,
pianificazione settimanale automatica.
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, session
from database import get_db
from ai_helpers import analizza_profilo_completo, genera_piano_editoriale, genera_post_da_piano
from routes.auth import get_org_id

log = logging.getLogger(__name__)

profilo_personale_bp = Blueprint("profilo_personale", __name__)


def _estrai_testo_profilo_completo(dati_prx: dict) -> str:
    """Formatta i dati Proxycurl come testo leggibile per Claude."""
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
    experiences = dati_prx.get("experiences") or dati_prx.get("experience") or []
    if experiences:
        parti.append("\nEsperienze professionali:")
        for exp in experiences[:5]:
            if not isinstance(exp, dict):
                continue
            titolo = exp.get("title") or exp.get("position") or ""
            azienda = exp.get("company") or exp.get("company_name") or ""
            desc = exp.get("description") or ""
            riga = f"  - {titolo}"
            if azienda:
                riga += f" @ {azienda}"
            if desc:
                riga += f": {desc[:120]}"
            parti.append(riga)
    education = dati_prx.get("education") or []
    if education:
        parti.append("\nFormazione:")
        for edu in education[:3]:
            if not isinstance(edu, dict):
                continue
            scuola = edu.get("school") or edu.get("institution") or ""
            grado = edu.get("degree_name") or edu.get("field_of_study") or ""
            if scuola or grado:
                parti.append(f"  - {grado} {scuola}".strip())
    skills = dati_prx.get("skills") or []
    if skills:
        if isinstance(skills[0], dict):
            nomi = [s.get("name", "") for s in skills[:15] if s.get("name")]
        else:
            nomi = [str(s) for s in skills[:15]]
        if nomi:
            parti.append(f"\nSkill: {', '.join(nomi)}")
    certs = dati_prx.get("certifications") or []
    if certs:
        nomi_c = [c.get("name", "") for c in certs[:5] if isinstance(c, dict) and c.get("name")]
        if nomi_c:
            parti.append(f"Certificazioni: {', '.join(nomi_c)}")
    return "\n".join(parti)


# ── Pagina principale ────────────────────────────────────────────────────────

@profilo_personale_bp.route("/profilo-personale")
def index():
    """Pagina analisi profilo personale — lista profili + ultima analisi."""
    org_id = get_org_id()
    user_id = session.get("user_id")
    db = get_db()

    # Profili personali salvati
    profili = db.execute(
        "SELECT * FROM profili_personali WHERE organizzazione_id = ? ORDER BY ultima_analisi DESC NULLS LAST",
        (org_id,)
    ).fetchall()
    profili = [dict(p) for p in profili]

    # Per ogni profilo, carica ultima analisi
    for p in profili:
        ultima = db.execute(
            "SELECT id, punteggio, headline_suggerita, about_suggerito, punti_forza, aree_miglioramento, keyword_mancanti, creato_il FROM analisi_profilo WHERE linkedin_url = ? AND organizzazione_id = ? ORDER BY creato_il DESC LIMIT 1",
            (p["linkedin_url"], org_id)
        ).fetchone()
        if ultima:
            p["ultima"] = dict(ultima)
            for campo in ("punti_forza", "aree_miglioramento", "keyword_mancanti"):
                if p["ultima"].get(campo):
                    try:
                        p["ultima"][campo] = json.loads(p["ultima"][campo])
                    except Exception:
                        p["ultima"][campo] = []
        else:
            p["ultima"] = None

    # Storico per utenti senza profilo salvato (backward compat)
    storico = db.execute(
        "SELECT id, linkedin_url, punteggio, creato_il FROM analisi_profilo WHERE organizzazione_id = ? ORDER BY creato_il DESC LIMIT 10",
        (org_id,)
    ).fetchall()

    db.close()
    return render_template(
        "profilo_personale.html",
        profili=profili,
        storico=[dict(r) for r in storico],
    )


# ── Analisi completa ─────────────────────────────────────────────────────────

@profilo_personale_bp.route("/profilo-personale/analizza", methods=["POST"])
def analizza():
    """Analisi completa: profilo + post LinkedIn."""
    dati = request.get_json() or {}
    linkedin_url = (dati.get("linkedin_url") or "").strip()
    testo_manuale = (dati.get("testo_manuale") or "").strip()

    if not linkedin_url and not testo_manuale:
        return jsonify({"errore": "Inserisci l'URL LinkedIn o incolla il testo del profilo."}), 400

    org_id = get_org_id()
    user_id = session.get("user_id")
    dati_prx = None
    post_linkedin = []

    # 1. Scrapa dati profilo via EnrichLayer
    if linkedin_url and "linkedin.com/in/" in linkedin_url:
        try:
            from proxycurl_helpers import arricchisci_profilo
            dati_prx = arricchisci_profilo(linkedin_url)
        except Exception as e:
            log.warning("EnrichLayer fallito: %s", e)

    # 2. Scrapa post LinkedIn via Apify
    if linkedin_url:
        try:
            from sources.linkedin_posts import scrapa_post_linkedin
            post_linkedin = scrapa_post_linkedin(linkedin_url, max_post=15)
        except Exception as e:
            log.warning("Scraping post fallito: %s", e)

    # Se nessun dato dal profilo, usa testo manuale
    if not dati_prx:
        if testo_manuale:
            dati_prx = {"summary": testo_manuale}
        else:
            return jsonify({
                "errore": "non_disponibile",
                "messaggio": "EnrichLayer non ha restituito dati. Incolla manualmente il testo del profilo."
            }), 422

    # 3. Analisi Claude completa
    try:
        risultato = analizza_profilo_completo(dati_prx, post_linkedin)
    except Exception as e:
        log.exception("analizza_profilo_completo fallita")
        return jsonify({"errore": f"Errore analisi AI: {str(e)}"}), 500

    # 4. Salva analisi
    prossima = datetime.utcnow() + timedelta(days=7)
    db = get_db()
    cur = db.execute(
        """INSERT INTO analisi_profilo
           (linkedin_url, punteggio, headline_attuale, headline_suggerita,
            about_attuale, about_suggerito, punti_forza, aree_miglioramento,
            keyword_mancanti, analisi_contenuti, consigli_contenuti,
            post_analizzati, prossima_analisi, dati_raw,
            organizzazione_id, utente_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            json.dumps(risultato.get("analisi_contenuti", {}), ensure_ascii=False),
            json.dumps(risultato.get("consigli_contenuti", []), ensure_ascii=False),
            len(post_linkedin),
            prossima.isoformat(),
            json.dumps(risultato, ensure_ascii=False),
            org_id,
            user_id,
        ),
    )
    analisi_id = cur.lastrowid

    # 5. Aggiorna/crea profilo_personale
    nome = dati_prx.get("first_name", "")
    cognome = dati_prx.get("last_name", "")
    headline = dati_prx.get("headline") or dati_prx.get("title") or ""
    foto = dati_prx.get("profile_pic_url") or ""
    settore = dati_prx.get("industry") or risultato.get("settore", "")
    connessioni = dati_prx.get("connections") or 0

    if linkedin_url:
        existing = db.execute(
            "SELECT id FROM profili_personali WHERE linkedin_url = ? AND organizzazione_id = ?",
            (linkedin_url, org_id)
        ).fetchone()
        if existing:
            db.execute(
                """UPDATE profili_personali SET nome=?, cognome=?, headline=?, foto_url=?,
                   settore=?, connessioni=?, ultima_analisi=CURRENT_TIMESTAMP,
                   prossima_analisi=? WHERE id=?""",
                (nome, cognome, headline, foto, settore, connessioni,
                 prossima.isoformat(), existing["id"])
            )
        else:
            db.execute(
                """INSERT INTO profili_personali
                   (utente_id, organizzazione_id, linkedin_url, nome, cognome,
                    headline, foto_url, settore, connessioni,
                    ultima_analisi, prossima_analisi)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
                (user_id, org_id, linkedin_url, nome, cognome,
                 headline, foto, settore, connessioni, prossima.isoformat())
            )

    db.commit()
    db.close()

    risultato["analisi_id"] = analisi_id
    risultato["post_analizzati"] = len(post_linkedin)
    return jsonify(risultato)


# ── Dettaglio analisi ─────────────────────────────────────────────────────────

@profilo_personale_bp.route("/profilo-personale/analisi/<int:analisi_id>")
def dettaglio_analisi(analisi_id):
    """Pagina dettaglio di un'analisi specifica."""
    org_id = get_org_id()
    db = get_db()
    row = db.execute(
        "SELECT * FROM analisi_profilo WHERE id = ? AND organizzazione_id = ?",
        (analisi_id, org_id)
    ).fetchone()
    if not row:
        db.close()
        return "Analisi non trovata", 404

    analisi = dict(row)
    for campo in ("punti_forza", "aree_miglioramento", "keyword_mancanti",
                   "analisi_contenuti", "consigli_contenuti", "dati_raw"):
        if analisi.get(campo):
            try:
                analisi[campo] = json.loads(analisi[campo])
            except Exception:
                pass

    # Storico punteggi per questo URL
    storico_punteggi = []
    if analisi.get("linkedin_url"):
        rows = db.execute(
            "SELECT punteggio, creato_il FROM analisi_profilo WHERE linkedin_url = ? AND organizzazione_id = ? ORDER BY creato_il ASC",
            (analisi["linkedin_url"], org_id)
        ).fetchall()
        storico_punteggi = [{"punteggio": r["punteggio"], "data": r["creato_il"]} for r in rows]

    db.close()
    return render_template(
        "profilo_personale_dettaglio.html",
        analisi=analisi,
        storico_punteggi=storico_punteggi,
    )


@profilo_personale_bp.route("/profilo-personale/<int:analisi_id>")
def dettaglio(analisi_id):
    """API JSON per caricamento analisi precedente (backward compat)."""
    org_id = get_org_id()
    db = get_db()
    row = db.execute(
        "SELECT * FROM analisi_profilo WHERE id = ? AND organizzazione_id = ?", (analisi_id, org_id)
    ).fetchone()
    db.close()
    if not row:
        return jsonify({"errore": "Analisi non trovata"}), 404
    r = dict(row)
    for campo in ("punti_forza", "aree_miglioramento", "keyword_mancanti",
                   "analisi_contenuti", "consigli_contenuti", "dati_raw"):
        if r.get(campo):
            try:
                r[campo] = json.loads(r[campo])
            except Exception:
                pass
    return jsonify(r)


# ── Piano editoriale ──────────────────────────────────────────────────────────

@profilo_personale_bp.route("/profilo-personale/genera-piano", methods=["POST"])
def genera_piano():
    """Genera un piano editoriale basato sull'analisi profilo."""
    dati = request.get_json() or {}
    analisi_id = dati.get("analisi_id")
    settimane = int(dati.get("settimane", 4))
    post_settimana = int(dati.get("post_settimana", 3))

    if not analisi_id:
        return jsonify({"errore": "analisi_id obbligatorio"}), 400

    org_id = get_org_id()
    user_id = session.get("user_id")
    db = get_db()

    row = db.execute(
        "SELECT * FROM analisi_profilo WHERE id = ? AND organizzazione_id = ?",
        (analisi_id, org_id)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"errore": "Analisi non trovata"}), 404

    analisi = dict(row)
    for campo in ("punti_forza", "aree_miglioramento", "keyword_mancanti",
                   "analisi_contenuti", "consigli_contenuti", "dati_raw"):
        if analisi.get(campo):
            try:
                analisi[campo] = json.loads(analisi[campo])
            except Exception:
                pass

    # Aggiungi nome dal profilo personale
    profilo = db.execute(
        "SELECT nome, cognome FROM profili_personali WHERE linkedin_url = ? AND organizzazione_id = ?",
        (analisi.get("linkedin_url", ""), org_id)
    ).fetchone()
    if profilo:
        analisi["nome"] = f"{profilo['nome'] or ''} {profilo['cognome'] or ''}".strip()

    # Estrai settore e tono da dati_raw
    dati_raw = analisi.get("dati_raw") or {}
    analisi.setdefault("settore", dati_raw.get("settore", ""))
    analisi.setdefault("tono_prevalente", dati_raw.get("tono_prevalente", ""))

    try:
        piano_posts = genera_piano_editoriale(analisi, settimane, post_settimana)
    except Exception as e:
        db.close()
        return jsonify({"errore": f"Errore generazione piano: {str(e)}"}), 500

    # Salva piano
    cur = db.execute(
        """INSERT INTO piani_editoriali (utente_id, organizzazione_id, analisi_profilo_id, settimane, post_settimana)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, org_id, analisi_id, settimane, post_settimana)
    )
    piano_id = cur.lastrowid

    # Salva post
    for p in piano_posts:
        db.execute(
            """INSERT INTO piano_post (piano_id, settimana, giorno_settimana, formato, tema, hook_suggerito, obiettivo, perche, emoji)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (piano_id, p.get("settimana", 1), p.get("giorno", ""),
             p.get("formato", "post_testo"), p.get("tema", ""),
             p.get("hook", ""), p.get("obiettivo", ""),
             p.get("perche", ""), p.get("emoji", ""))
        )

    db.commit()
    db.close()
    return jsonify({"ok": True, "piano_id": piano_id})


@profilo_personale_bp.route("/profilo-personale/piano/<int:piano_id>")
def piano_dettaglio(piano_id):
    """Pagina piano editoriale."""
    org_id = get_org_id()
    db = get_db()

    piano = db.execute(
        "SELECT * FROM piani_editoriali WHERE id = ? AND organizzazione_id = ?",
        (piano_id, org_id)
    ).fetchone()
    if not piano:
        db.close()
        return "Piano non trovato", 404

    piano = dict(piano)
    posts = db.execute(
        "SELECT * FROM piano_post WHERE piano_id = ? ORDER BY settimana, id",
        (piano_id,)
    ).fetchall()
    posts = [dict(p) for p in posts]

    # Raggruppa per settimana
    settimane = {}
    for p in posts:
        s = p["settimana"]
        if s not in settimane:
            settimane[s] = []
        settimane[s].append(p)

    # Carica analisi collegata per il breadcrumb
    analisi = None
    if piano.get("analisi_profilo_id"):
        analisi = db.execute(
            "SELECT id, linkedin_url FROM analisi_profilo WHERE id = ?",
            (piano["analisi_profilo_id"],)
        ).fetchone()
        if analisi:
            analisi = dict(analisi)

    db.close()

    totale = len(posts)
    generati = sum(1 for p in posts if p.get("generato"))

    return render_template(
        "piano_editoriale.html",
        piano=piano,
        settimane=settimane,
        analisi=analisi,
        totale_post=totale,
        post_generati=generati,
    )


@profilo_personale_bp.route("/profilo-personale/piano/<int:piano_id>/genera-post/<int:post_id>", methods=["POST"])
def genera_post(piano_id, post_id):
    """Genera il testo completo di un post del piano."""
    org_id = get_org_id()
    db = get_db()

    piano = db.execute(
        "SELECT * FROM piani_editoriali WHERE id = ? AND organizzazione_id = ?",
        (piano_id, org_id)
    ).fetchone()
    if not piano:
        db.close()
        return jsonify({"errore": "Piano non trovato"}), 404

    post = db.execute(
        "SELECT * FROM piano_post WHERE id = ? AND piano_id = ?",
        (post_id, piano_id)
    ).fetchone()
    if not post:
        db.close()
        return jsonify({"errore": "Post non trovato"}), 404

    post = dict(post)

    # Carica dati profilo dall'analisi
    profilo_info = {"nome": "", "settore": "", "headline": "", "tono_prevalente": ""}
    if piano["analisi_profilo_id"]:
        analisi_row = db.execute(
            "SELECT dati_raw, linkedin_url FROM analisi_profilo WHERE id = ?",
            (piano["analisi_profilo_id"],)
        ).fetchone()
        if analisi_row:
            dati_raw = {}
            if analisi_row["dati_raw"]:
                try:
                    dati_raw = json.loads(analisi_row["dati_raw"])
                except Exception:
                    pass
            profilo_info["settore"] = dati_raw.get("settore", "")
            profilo_info["tono_prevalente"] = dati_raw.get("tono_prevalente", "professionale e diretto")

            pp = db.execute(
                "SELECT nome, cognome, headline FROM profili_personali WHERE linkedin_url = ? AND organizzazione_id = ?",
                (analisi_row.get("linkedin_url", ""), org_id)
            ).fetchone()
            if pp:
                profilo_info["nome"] = f"{pp['nome'] or ''} {pp['cognome'] or ''}".strip()
                profilo_info["headline"] = pp.get("headline", "")

    try:
        testo = genera_post_da_piano(post, profilo_info)
    except Exception as e:
        db.close()
        return jsonify({"errore": f"Errore generazione: {str(e)}"}), 500

    db.execute(
        "UPDATE piano_post SET testo_generato = ?, generato = TRUE WHERE id = ?",
        (testo, post_id)
    )
    db.commit()
    db.close()

    return jsonify({"ok": True, "testo": testo})


@profilo_personale_bp.route("/profilo-personale/piano/<int:piano_id>/aggiorna", methods=["PUT"])
def aggiorna_piano(piano_id):
    """Aggiorna settimane/post_settimana e rigenera il piano."""
    dati = request.get_json() or {}
    settimane = int(dati.get("settimane", 4))
    post_settimana = int(dati.get("post_settimana", 3))

    org_id = get_org_id()
    db = get_db()

    piano = db.execute(
        "SELECT * FROM piani_editoriali WHERE id = ? AND organizzazione_id = ?",
        (piano_id, org_id)
    ).fetchone()
    if not piano:
        db.close()
        return jsonify({"errore": "Piano non trovato"}), 404

    piano = dict(piano)

    # Carica analisi
    analisi_row = db.execute(
        "SELECT * FROM analisi_profilo WHERE id = ?",
        (piano["analisi_profilo_id"],)
    ).fetchone()
    if not analisi_row:
        db.close()
        return jsonify({"errore": "Analisi collegata non trovata"}), 404

    analisi = dict(analisi_row)
    for campo in ("punti_forza", "aree_miglioramento", "keyword_mancanti",
                   "analisi_contenuti", "dati_raw"):
        if analisi.get(campo):
            try:
                analisi[campo] = json.loads(analisi[campo])
            except Exception:
                pass

    profilo = db.execute(
        "SELECT nome, cognome FROM profili_personali WHERE linkedin_url = ? AND organizzazione_id = ?",
        (analisi.get("linkedin_url", ""), org_id)
    ).fetchone()
    if profilo:
        analisi["nome"] = f"{profilo['nome'] or ''} {profilo['cognome'] or ''}".strip()

    dati_raw = analisi.get("dati_raw") or {}
    analisi.setdefault("settore", dati_raw.get("settore", ""))

    try:
        piano_posts = genera_piano_editoriale(analisi, settimane, post_settimana)
    except Exception as e:
        db.close()
        return jsonify({"errore": f"Errore rigenerazione: {str(e)}"}), 500

    # Cancella vecchi post e aggiorna piano
    db.execute("DELETE FROM piano_post WHERE piano_id = ?", (piano_id,))
    db.execute(
        "UPDATE piani_editoriali SET settimane = ?, post_settimana = ? WHERE id = ?",
        (settimane, post_settimana, piano_id)
    )

    for p in piano_posts:
        db.execute(
            """INSERT INTO piano_post (piano_id, settimana, giorno_settimana, formato, tema, hook_suggerito, obiettivo, perche, emoji)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (piano_id, p.get("settimana", 1), p.get("giorno", ""),
             p.get("formato", "post_testo"), p.get("tema", ""),
             p.get("hook", ""), p.get("obiettivo", ""),
             p.get("perche", ""), p.get("emoji", ""))
        )

    db.commit()
    db.close()
    return jsonify({"ok": True, "piano_id": piano_id})


# ── Salva profilo voce ────────────────────────────────────────────────────────

@profilo_personale_bp.route("/profilo-personale/salva-profilo-voce", methods=["POST"])
def salva_profilo_voce():
    """Salva i dati estratti come profilo voce per la sezione Contenuti."""
    dati = request.get_json() or {}
    nome = (dati.get("nome") or "").strip()
    linkedin_url = (dati.get("linkedin_url") or "").strip()
    bio_breve = (dati.get("bio_breve") or "").strip()
    tono = (dati.get("tono_prevalente") or "").strip()
    settore = (dati.get("settore") or "").strip()

    if not nome:
        return jsonify({"errore": "Il nome e' obbligatorio."}), 400

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


# ── Analisi settimanale automatica ────────────────────────────────────────────

def analisi_settimanale_automatica():
    """Controlla profili con prossima_analisi scaduta e lancia analisi in background."""
    from database import get_db as _get_db
    db = _get_db()
    try:
        profili = db.execute("""
            SELECT * FROM profili_personali
            WHERE prossima_analisi <= CURRENT_TIMESTAMP
            AND linkedin_url IS NOT NULL
        """).fetchall()
    except Exception:
        profili = []
    db.close()

    for profilo in profili:
        threading.Thread(
            target=_esegui_analisi_profilo_background,
            args=(dict(profilo),),
            daemon=True
        ).start()

    return len(profili)


def _esegui_analisi_profilo_background(profilo: dict):
    """Esegue analisi in background per un singolo profilo."""
    from database import get_db as _get_db
    linkedin_url = profilo["linkedin_url"]
    org_id = profilo["organizzazione_id"]
    user_id = profilo.get("utente_id")

    try:
        from proxycurl_helpers import arricchisci_profilo
        dati_prx = arricchisci_profilo(linkedin_url)
    except Exception as e:
        log.warning("Background analisi — EnrichLayer fallito per %s: %s", linkedin_url, e)
        return

    if not dati_prx:
        return

    post_linkedin = []
    try:
        from sources.linkedin_posts import scrapa_post_linkedin
        post_linkedin = scrapa_post_linkedin(linkedin_url, max_post=15)
    except Exception:
        pass

    try:
        risultato = analizza_profilo_completo(dati_prx, post_linkedin)
    except Exception as e:
        log.error("Background analisi — Claude fallito per %s: %s", linkedin_url, e)
        return

    prossima = datetime.utcnow() + timedelta(days=7)
    db = _get_db()
    db.execute(
        """INSERT INTO analisi_profilo
           (linkedin_url, punteggio, headline_attuale, headline_suggerita,
            about_attuale, about_suggerito, punti_forza, aree_miglioramento,
            keyword_mancanti, analisi_contenuti, consigli_contenuti,
            post_analizzati, prossima_analisi, dati_raw,
            organizzazione_id, utente_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            json.dumps(risultato.get("analisi_contenuti", {}), ensure_ascii=False),
            json.dumps(risultato.get("consigli_contenuti", []), ensure_ascii=False),
            len(post_linkedin),
            prossima.isoformat(),
            json.dumps(risultato, ensure_ascii=False),
            org_id,
            user_id,
        ),
    )
    db.execute(
        "UPDATE profili_personali SET ultima_analisi=CURRENT_TIMESTAMP, prossima_analisi=? WHERE id=?",
        (prossima.isoformat(), profilo["id"])
    )
    db.commit()
    db.close()
    log.info("Background analisi completata per %s", linkedin_url)
