"""
Helper per le chiamate all'API Anthropic Claude.
Contiene tutte le funzioni AI usate dai vari moduli dell'app.
"""

import anthropic
import os
import json
import re
import logging

# Model ID Claude Opus 4.7
CLAUDE_MODEL = "claude-sonnet-4-5"

logger = logging.getLogger(__name__)


def get_client():
    """Crea e restituisce il client Anthropic."""
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def clean_text(testo: str) -> str:
    """
    Sanitizza il testo prima di mandarlo all'API:
    - Forza encoding UTF-8 rimuovendo caratteri non validi
    - Normalizza spazi e a capo
    - Rimuove caratteri di controllo (eccetto \\n e \\t)
    """
    if not testo:
        return ""
    # Forza stringa Python, rimuovi caratteri non-UTF8
    if isinstance(testo, bytes):
        testo = testo.decode("utf-8", errors="ignore")
    # Rimuovi caratteri di controllo non stampabili (mantieni \n \t \r)
    testo = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", testo)
    # Normalizza spazi multipli e righe vuote eccessive
    testo = re.sub(r"\n{3,}", "\n\n", testo)
    testo = testo.strip()
    return testo


def _log_payload(funzione: str, payload: dict):
    """Logga il payload completo prima di ogni chiamata API."""
    logger.info(
        "[AI] %s → model=%s max_tokens=%s messages_count=%d first_content_preview=%s",
        funzione,
        payload.get("model"),
        payload.get("max_tokens"),
        len(payload.get("messages", [])),
        str(payload.get("messages", [{}])[0].get("content", ""))[:120],
    )


def _chiama_api(funzione: str, payload: dict):
    """
    Esegue la chiamata all'API Anthropic con logging completo.
    Lancia l'eccezione originale in caso di errore, dopo aver loggato il response body.
    """
    # Validazioni difensive
    assert isinstance(payload["model"], str), "model deve essere una stringa"
    assert isinstance(payload["max_tokens"], int), "max_tokens deve essere un intero"
    assert isinstance(payload["messages"], list) and len(payload["messages"]) > 0, \
        "messages deve essere una lista non vuota"
    for m in payload["messages"]:
        assert isinstance(m.get("role"), str), "ogni messaggio deve avere role stringa"
        assert isinstance(m.get("content"), str), "ogni messaggio deve avere content stringa"

    _log_payload(funzione, payload)

    client = get_client()
    try:
        risposta = client.messages.create(**payload)
        return risposta
    except anthropic.APIStatusError as e:
        logger.error(
            "[AI] %s → APIStatusError status=%s body=%s",
            funzione, e.status_code, e.response.text if hasattr(e, "response") else str(e),
            exc_info=True,
        )
        raise
    except anthropic.APIError as e:
        logger.error("[AI] %s → APIError: %s", funzione, str(e), exc_info=True)
        raise
    except Exception as e:
        logger.error("[AI] %s → %s: %s", funzione, type(e).__name__, str(e), exc_info=True)
        raise


def test_connessione_api() -> dict:
    """
    Chiama l'API con un payload minimale per verificare la connettività.
    Restituisce {"ok": True} oppure {"ok": False, "errore": "..."}.
    """
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "test"}],
    }
    try:
        _chiama_api("test_connessione_api", payload)
        logger.info("[AI] test_connessione_api → OK")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "errore": str(e)}


def _build_prompt_completo(scopo: str, scopo_dettaglio: str, impostazioni: dict, testo_profilo: str) -> str:
    """
    Costruisce il prompt completo per analisi profilo LinkedIn.
    Ogni scopo ha prompt, criteri di valutazione e regole completamente dedicati.
    """
    imp = impostazioni or {}

    # ── Sezione profilo target (comune a tutti gli scopi) ──
    profilo_target_block = (
        "PROFILO TARGET CONFIGURATO:\n"
        f"- Nome profilo: {imp.get('nome', 'non specificato')}\n"
        f"- Scopo: {scopo}\n"
        f"- Dettaglio scopo: {scopo_dettaglio or 'non specificato'}\n"
        f"- Ruoli cercati: {imp.get('ruoli_target', 'non specificato')}\n"
        f"- Settori: {imp.get('settori', 'non specificato')}\n"
        f"- Anni esperienza minimi: {imp.get('anni_esperienza_min', 0)}\n"
        f"- Eta min/max: {imp.get('eta_min', 'non specificata')}/{imp.get('eta_max', 'non specificata')}\n"
        f"- Keyword positive (presenza aumenta punteggio): {imp.get('keyword_positive', 'nessuna')}\n"
        f"- Keyword negative (presenza riduce punteggio): {imp.get('keyword_negative', 'nessuna')}\n\n"
    ) if imp else ""

    # ── JSON output (identico per tutti gli scopi) ──
    def _json_schema(punteggio_desc, analisi_desc, spunti_desc, msg_desc):
        return (
            "Rispondi ESCLUSIVAMENTE con questo JSON valido, senza testo prima o dopo:\n"
            "{\n"
            '  "nome_contatto": "<nome e cognome estratto dal profilo, o null>",\n'
            '  "ruolo_attuale": "<ruolo professionale attuale, o null>",\n'
            '  "azienda": "<azienda attuale, o null>",\n'
            '  "anni_esperienza": <numero intero stimato, o null>,\n'
            f'  "punteggio": <{punteggio_desc}>,\n'
            f'  "analisi_percorso": "<{analisi_desc}>",\n'
            '  "spunti_contatto": [\n'
            f'    "<{spunti_desc} 1>",\n'
            f'    "<{spunti_desc} 2>",\n'
            f'    "<{spunti_desc} 3>"\n'
            '  ],\n'
            f'  "messaggio_outreach": "<{msg_desc}>"\n'
            "}"
        )

    # ── Regole assolute per il punteggio ──
    regole_base = (
        "REGOLE ASSOLUTE PER IL PUNTEGGIO:\n"
        "1. Se keyword negative sono presenti nel profilo → punteggio massimo 4/10\n"
        "2. Se ruoli target NON corrispondono affatto al profilo → punteggio massimo 3/10\n"
    )

    # ══════════════════════════════════════════════════════════════
    # SALES — stai cercando clienti per un prodotto/servizio
    # ══════════════════════════════════════════════════════════════
    if scopo == 'sales':
        return (
            "Sei un esperto di sales B2B e lead qualification italiano.\n\n"
            "COMPITO: Valuta questo profilo LinkedIn come POTENZIALE CLIENTE per un prodotto/servizio.\n"
            "NON stai facendo recruiting. NON valutare carriera, ambizioni, cambio lavoro.\n\n"
            f"PRODOTTO/SERVIZIO DA VENDERE: {scopo_dettaglio}\n\n"
            + profilo_target_block
            + "CRITERI DI VALUTAZIONE (qualita del lead):\n"
            "- Il profilo ha il problema che il prodotto risolve? → fondamentale\n"
            "- Ha ruolo decisionale (manager, direttore, responsabile, founder, owner)? → +punti alti\n"
            "- E nel settore target corretto? → +punti\n"
            "- Dimensione azienda compatibile? → +punti\n"
            "- Seniority alta? → +punti (piu budget)\n"
            "- Junior o neolaureato? → -punti (poco budget decisionale)\n"
            "- Keyword positive trovate nel profilo? → +punti\n"
            "- Keyword negative trovate? → -punti\n"
            "- MAI valutare disponibilita al cambio lavoro — non e rilevante\n\n"
            "SCALA PUNTEGGIO (1-10):\n"
            "- 8-10: Decision maker nel settore target, ruolo con budget, chiaramente ha il problema che il prodotto risolve\n"
            "- 6-7: Settore giusto, ruolo rilevante ma seniority media o potere decisionale incerto\n"
            "- 4-5: Settore correlato ma non core, oppure ruolo troppo operativo\n"
            "- 1-3: Settore completamente diverso o nessun legame con il prodotto\n\n"
            "REGOLA CRITICA SUI DATI DISPONIBILI:\n"
            "I profili possono arrivare da scraping con solo headline e nome (dati limitati).\n"
            "NON penalizzare MAI per 'profilo incompleto' o 'informazioni insufficienti'.\n"
            "Valuta con quello che hai a disposizione:\n"
            "- Se l'headline contiene parole come 'recruiter', 'HR', 'talent acquisition', "
            "'head hunter', 'selezione', 'recruiting', 'risorse umane' e questi sono nel settore target "
            "→ questo e SUFFICIENTE per dare 7+/10\n"
            "- Un profilo con headline chiara nel settore target vale 7-8/10 anche senza altri dati\n"
            "- Dai il beneficio del dubbio: se il ruolo e nel settore target, punteggio minimo 6/10\n"
            "- Non richiedere informazioni aggiuntive per dare un punteggio alto\n\n"
            + regole_base
            + "3. Se il profilo e chiaramente nel settore target → punteggio minimo 6/10\n"
            "4. Se il profilo ha ruolo decisionale nel settore target → punteggio minimo 8/10\n"
            "5. NON menzionare mai cambio lavoro, carriera, opportunita professionali\n\n"
            f"PROFILO LINKEDIN DA ANALIZZARE:\n{testo_profilo}\n\n"
            + _json_schema(
                "1-10, qualita del lead commerciale",
                "3-4 frasi: perche e o non e un buon prospect per questo prodotto, "
                "che problema ha che il prodotto risolve, che ruolo decisionale ha",
                "aggancio commerciale personalizzato",
                "messaggio di vendita consultiva LinkedIn, max 300 caratteri, "
                "apre conversazione sul problema che il prodotto risolve, "
                "parla del valore del prodotto per lui, MAI parlare di lavoro/carriera"
            )
        )

    # ══════════════════════════════════════════════════════════════
    # PARTNERSHIP — stai cercando collaboratori o partner commerciali
    # ══════════════════════════════════════════════════════════════
    if scopo == 'partnership':
        return (
            "Sei un esperto di business development e partnership strategiche italiano.\n\n"
            "COMPITO: Valuta questo profilo LinkedIn come POTENZIALE PARTNER commerciale.\n"
            "NON stai facendo recruiting. NON valutare se questa persona cerca lavoro.\n\n"
            f"TIPO DI PARTNERSHIP CERCATA: {scopo_dettaglio}\n\n"
            + profilo_target_block
            + "CRITERI DI VALUTAZIONE (potenziale come partner):\n"
            "- Opera in settore complementare al tuo? → +punti\n"
            "- Ha competenze che si integrano con le tue? → +punti\n"
            "- Ha una rete di contatti rilevante? → +punti\n"
            "- E un freelance/consulente/libero professionista? → +punti (piu flessibile)\n"
            "- Ha gia esperienze di collaborazione o partnership? → +punti\n"
            "- Competitor diretto? → -punti\n"
            "- Keyword positive trovate nel profilo? → +punti\n"
            "- Keyword negative trovate? → -punti\n\n"
            "SCALA PUNTEGGIO (1-10):\n"
            "- 8-10: Competenze complementari perfette, rete di contatti nel settore target, "
            "esperienza in collaborazioni simili\n"
            "- 6-7: Settore giusto e competenze rilevanti, sovrapposizione parziale\n"
            "- 4-5: Qualche punto di contatto ma partnership non ovvia\n"
            "- 1-3: Nessuna sinergia evidente o competitor diretto\n\n"
            + regole_base
            + "3. Profilo incompleto o con informazioni insufficienti → penalizza il punteggio\n\n"
            f"PROFILO LINKEDIN DA ANALIZZARE:\n{testo_profilo}\n\n"
            + _json_schema(
                "1-10, potenziale come partner",
                "3-4 frasi: che sinergie ci sono, cosa puo portare alla partnership, "
                "come si integrano le competenze",
                "spunto per proporre collaborazione",
                "messaggio LinkedIn che propone collaborazione win-win, "
                "max 300 caratteri, spiega il vantaggio reciproco"
            )
        )

    # ══════════════════════════════════════════════════════════════
    # NETWORK — stai costruendo la tua rete professionale
    # ══════════════════════════════════════════════════════════════
    if scopo == 'network':
        return (
            "Sei un esperto di networking professionale italiano.\n\n"
            "COMPITO: Valuta questo profilo LinkedIn per capire se vale la pena connettersi.\n"
            "NON stai facendo recruiting ne vendita.\n\n"
            f"MOTIVO DEL NETWORKING: {scopo_dettaglio or 'espansione rete professionale'}\n\n"
            + profilo_target_block
            + "CRITERI DI VALUTAZIONE (interesse della connessione):\n"
            "- Opera nello stesso settore o settore adiacente? → +punti\n"
            "- Ha un profilo attivo con post e engagement? → +punti\n"
            "- Ha connessioni in comune rilevanti? → +punti\n"
            "- Profilo influente nel settore (molte connessioni, post virali)? → +punti alti\n"
            "- Keyword positive trovate nel profilo? → +punti\n"
            "- Profilo inattivo o senza informazioni? → -punti\n\n"
            "SCALA PUNTEGGIO (1-10):\n"
            "- 8-10: Persona molto influente nel settore, interessi fortemente allineati\n"
            "- 6-7: Settore rilevante, potenziale scambio di valore\n"
            "- 4-5: Qualche punto in comune ma connessione non prioritaria\n"
            "- 1-3: Nessun punto di contatto evidente\n\n"
            + regole_base
            + "3. Profilo incompleto o con informazioni insufficienti → penalizza il punteggio\n\n"
            f"PROFILO LINKEDIN DA ANALIZZARE:\n{testo_profilo}\n\n"
            + _json_schema(
                "1-10, interesse nel connettersi",
                "3-4 frasi: perche e interessante connettersi, cosa avete in comune, "
                "che valore puo portare alla rete",
                "spunto per connettersi",
                "messaggio LinkedIn leggero e genuino, max 300 caratteri, "
                "tono amichevole, focalizzato su interessi comuni o settore condiviso"
            )
        )

    # ══════════════════════════════════════════════════════════════
    # RECRUITING (default) — stai cercando qualcuno da assumere
    # ══════════════════════════════════════════════════════════════

    # Pesi configurabili (solo recruiting li usa)
    istr_pesi = ""
    if imp:
        p_eta = imp.get('peso_eta', 5)
        p_esp = imp.get('peso_esperienza', 5)
        p_set = imp.get('peso_settore', 5)
        p_ruo = imp.get('peso_ruolo', 5)
        p_kw  = imp.get('peso_keyword', 5)
        istr_pesi = (
            "\nPESI PER IL PUNTEGGIO (scala 0-10, 0=ignora, 10=determinante):\n"
            f"- Eta nel range target: {p_eta}/10\n"
            f"- Anni di esperienza: {p_esp}/10\n"
            f"- Settore di provenienza: {p_set}/10\n"
            f"- Corrispondenza ruolo target: {p_ruo}/10\n"
            f"- Parole chiave positive/negative: {p_kw}/10\n"
        )

    return (
        "Sei un esperto recruiter e talent acquisition italiano.\n\n"
        "COMPITO: Valuta questo profilo LinkedIn come POTENZIALE CANDIDATO da assumere.\n\n"
        + (f"POSIZIONE CERCATA: {scopo_dettaglio}\n\n" if scopo_dettaglio else "")
        + profilo_target_block
        + "CRITERI DI VALUTAZIONE (idoneita come candidato):\n"
        "- Ruoli target presenti nel profilo? → +punti\n"
        "- Anni di esperienza >= anni_esperienza_min? → +punti\n"
        "- Keyword positive trovate nel profilo? → +punti\n"
        "- Keyword negative trovate? → -punti\n"
        "- Settore corrispondente? → +punti\n"
        "- Profilo incompleto o informazioni insufficienti? → -punti\n\n"
        "SCALA PUNTEGGIO (1-10):\n"
        "- 8-10: Match eccellente — ruolo, settore, esperienza e competenze perfettamente allineati\n"
        "- 6-7: Buon match — la maggior parte dei criteri soddisfatti, qualche gap minore\n"
        "- 4-5: Match parziale — alcuni criteri soddisfatti ma gap significativi\n"
        "- 1-3: Match scarso — profilo non adatto ai criteri richiesti\n"
        + istr_pesi + "\n"
        + regole_base
        + "3. Profilo incompleto o con informazioni insufficienti → penalizza il punteggio\n"
        "4. Valuta ESCLUSIVAMENTE idoneita al ruolo cercato\n\n"
        f"PROFILO LINKEDIN DA ANALIZZARE:\n{testo_profilo}\n\n"
        + _json_schema(
            "1-10, idoneita come candidato",
            "3-4 frasi: analisi competenze, percorso professionale, fit con la posizione cercata",
            "spunto personalizzato per il primo contatto",
            "messaggio LinkedIn professionale, max 300 caratteri, "
            "parla di opportunita di carriera e crescita professionale"
        )
    )


def analizza_profilo_linkedin(testo_profilo: str, tipo_profilo: str, impostazioni: dict = None) -> dict:
    """
    Analizza un profilo LinkedIn e restituisce valutazione strutturata.
    tipo_profilo: 'A' = Senior, 'B' = Under 35
    """
    testo_profilo = clean_text(testo_profilo)
    scopo = (impostazioni or {}).get('scopo', 'recruiting')
    scopo_dettaglio = (impostazioni or {}).get('scopo_dettaglio', '')

    prompt = _build_prompt_completo(scopo, scopo_dettaglio, impostazioni, testo_profilo)

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 1500,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("analizza_profilo_linkedin", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        return json.loads(testo)
    except Exception as e:
        logger.error("[AI] analizza_profilo_linkedin fallita: %s", e)
        raise


def analizza_profilo_arricchito(
    testo_profilo: str,
    tipo_profilo: str,
    dati_prx: dict,
    dati_base: dict,
) -> dict:
    """
    Seconda analisi Claude con dati Proxycurl arricchiti.
    Restituisce i campi predittivi aggiuntivi (punteggio_compatibilita,
    indice_mobilita, pattern_carriera, ecc.).
    In caso di errore restituisce un dict vuoto (il caller usa i dati base).
    """
    from proxycurl_helpers import estrai_testo_proxycurl

    testo_prx = estrai_testo_proxycurl(dati_prx)
    base_str = json.dumps(
        {k: dati_base.get(k) for k in ["punteggio", "analisi_percorso", "ruolo_attuale", "azienda", "anni_esperienza"]},
        ensure_ascii=False,
    )

    prompt = (
        "Sei un esperto recruiter.\n"
        "Disponi di un'analisi base già effettuata e di dati arricchiti da Proxycurl.\n\n"
        f"ANALISI BASE:\n{base_str}\n\n"
        f"TESTO PROFILO:\n{clean_text(testo_profilo)[:1500]}\n\n"
        f"DATI ARRICCHITI PROXYCURL:\n{testo_prx}\n\n"
        "Fornisci una valutazione predittiva completa ESCLUSIVAMENTE in questo formato JSON valido:\n"
        "{\n"
        '  "punteggio_finale": <1-10, aggiornato con tutti i dati>,\n'
        '  "punteggio_compatibilita": <1-10>,\n'
        '  "indice_mobilita": <1-10, probabilità di essere aperto a nuove opportunità>,\n'
        '  "punteggio_qualita_profilo": <1-10, completezza e cura del profilo LinkedIn>,\n'
        '  "pattern_carriera": "<stabile|dinamico|in_stallo|in_crescita|instabile>",\n'
        '  "momento_contatto": "<ora|6_mesi|1_anno|non_adatto>",\n'
        '  "motivazione_probabile": "<1-2 frasi su perché potrebbe essere interessato>",\n'
        '  "segnali_positivi": ["<segnale 1>", "<segnale 2>", "<segnale 3>"],\n'
        '  "segnali_negativi": ["<segnale 1>", "<segnale 2>"],\n'
        '  "rischi": ["<rischio 1>", "<rischio 2>"],\n'
        '  "analisi_attivita": "<analisi breve dell\'attività LinkedIn recente>",\n'
        '  "messaggio_personalizzato": "<bozza messaggio LinkedIn personalizzato, max 300 caratteri>",\n'
        '  "sintesi": "<sintesi del profilo e opportunità in 2-3 righe>"\n'
        "}"
    )

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("analizza_profilo_arricchito", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        result = json.loads(testo)
        # Usa punteggio_finale per sovrascrivere il punteggio base
        if "punteggio_finale" in result:
            result["punteggio"] = result["punteggio_finale"]
        return result
    except Exception as e:
        logger.error("[AI] analizza_profilo_arricchito fallita: %s", e)
        return {}


def analizza_profilo_linkedin_stream(
    testo_profilo: str,
    tipo_profilo: str,
    impostazioni: dict = None,
    linkedin_url: str = None,
    dati_proxycurl_cached: dict = None,
):
    """
    Versione streaming di analizza_profilo_linkedin().
    Genera eventi SSE:
      - {"type":"chunk","text":"..."}        — testo grezzo in arrivo da Claude
      - {"type":"arricchimento_start"}       — Proxycurl in corso (solo se applicabile)
      - {"type":"done","risultato":{}}        — analisi completa, JSON parsato
      - {"type":"errore","messaggio":"..."}  — in caso di errore

    Se punteggio base >= 6 e linkedin_url disponibile:
      - Chiama Proxycurl (o usa cache se < 30 giorni)
      - Esegue seconda analisi Claude con dati arricchiti
    """
    print(f"=== ANALISI START: linkedin_url={linkedin_url} ===", flush=True)
    testo_profilo = clean_text(testo_profilo)

    scopo_s = (impostazioni or {}).get('scopo', 'recruiting')
    scopo_dettaglio_s = (impostazioni or {}).get('scopo_dettaglio', '')

    # Usa lo stesso prompt builder della versione non-streaming
    prompt = _build_prompt_completo(scopo_s, scopo_dettaglio_s, impostazioni, testo_profilo)

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 1500,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }

    client = get_client()
    testo_accumulato = ""

    try:
        with client.messages.stream(**payload) as stream:
            for chunk in stream.text_stream:
                testo_accumulato += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk}, ensure_ascii=False)}\n\n"

        # Stream completato — parse JSON finale
        testo_pulito = testo_accumulato.strip()
        if testo_pulito.startswith("```"):
            testo_pulito = testo_pulito.split("```")[1]
            if testo_pulito.startswith("json"):
                testo_pulito = testo_pulito[4:]
        risultato = json.loads(testo_pulito)

        # ── Arricchimento Proxycurl (solo se punteggio >= 6 e URL disponibile) ──
        risultato["arricchito"] = False
        punteggio_base = risultato.get("punteggio", 0) or 0
        print(f"=== PUNTEGGIO BASE: {punteggio_base} ===", flush=True)
        if punteggio_base >= 5 and (linkedin_url or dati_proxycurl_cached):
            yield f"data: {json.dumps({'type': 'arricchimento_start'}, ensure_ascii=False)}\n\n"
            try:
                from proxycurl_helpers import arricchisci_profilo, is_cache_valida
                dati_prx = None
                # Usa cache se valida
                if dati_proxycurl_cached and is_cache_valida(dati_proxycurl_cached):
                    dati_prx = dati_proxycurl_cached
                    logger.info("[AI] Proxycurl: uso cache per %s", linkedin_url)
                elif linkedin_url:
                    print(f"=== ENRICHLAYER START: url={linkedin_url} ===", flush=True)
                    dati_prx = arricchisci_profilo(linkedin_url)
                    print(f"=== ENRICHLAYER DONE: campi={len(dati_prx) if dati_prx else 0} ===", flush=True)
                else:
                    print(f"=== ENRICHLAYER SKIP: nessun linkedin_url disponibile ===", flush=True)

                if dati_prx:
                    enriched = analizza_profilo_arricchito(testo_profilo, tipo_profilo, dati_prx, risultato)
                    if enriched:
                        risultato.update(enriched)
                        risultato["arricchito"] = True
                        # Tieni dati_proxycurl separato: yield come evento interno
                        # (intercettato dal route, non inoltrato al browser)
                        yield f"data: {json.dumps({'type': '_proxycurl_data', 'dati': dati_prx}, ensure_ascii=False)}\n\n"
            except Exception as e_prx:
                logger.error("[AI] Errore arricchimento Proxycurl: %s", e_prx)
                print(f"=== ENRICHLAYER ERROR: {e_prx} ===", flush=True)
        else:
            print(f"=== ENRICHLAYER SKIP: punteggio={punteggio_base} linkedin_url={linkedin_url} ===", flush=True)

        # done event senza dati_proxycurl (evita payload > 20 KB che rompe JSON.parse nel browser)
        risultato.pop("dati_proxycurl", None)
        arricchito = risultato.get("arricchito", False)
        print(f"=== SSE DONE: arricchito={arricchito} campi={list(risultato.keys())} ===", flush=True)
        yield f"data: {json.dumps({'type': 'done', 'risultato': risultato}, ensure_ascii=False)}\n\n"

    except json.JSONDecodeError as e:
        logger.error("[AI] analizza_profilo_linkedin_stream — JSON parse fallito: %s | testo: %s", e, testo_accumulato[:200])
        yield f"data: {json.dumps({'type': 'errore', 'messaggio': 'Risposta AI non parsabile come JSON.'})}\n\n"
    except Exception as e:
        logger.error("[AI] analizza_profilo_linkedin_stream — errore: %s", e, exc_info=True)
        yield f"data: {json.dumps({'type': 'errore', 'messaggio': str(e)})}\n\n"


def rigenera_messaggio_outreach(testo_profilo: str, messaggio_attuale: str, istruzioni: str = "") -> str:
    """Rigenera il messaggio di outreach (nuova variante o riscritto con istruzioni)."""
    testo_profilo    = clean_text(testo_profilo)
    messaggio_attuale = clean_text(messaggio_attuale)
    istruzioni        = clean_text(istruzioni)

    if istruzioni:
        prompt = (
            "Sei un recruiter esperto. Riscrivi il seguente messaggio di outreach LinkedIn\n"
            f"seguendo queste istruzioni: {istruzioni}\n\n"
            "MESSAGGIO ATTUALE:\n"
            f"{messaggio_attuale}\n\n"
            "PROFILO DEL CANDIDATO (contesto):\n"
            f"{testo_profilo[:500]}\n\n"
            "Riscrivi SOLO il testo del messaggio, senza intestazioni o spiegazioni. Max 300 caratteri."
        )
    else:
        prompt = (
            "Sei un recruiter esperto. Genera una NUOVA variante del messaggio di outreach LinkedIn\n"
            "per questo candidato. Deve essere diversa dalla versione precedente, mantenendo tono professionale e umano.\n\n"
            "PROFILO DEL CANDIDATO:\n"
            f"{testo_profilo[:500]}\n\n"
            "VERSIONE PRECEDENTE (da cui differenziarti):\n"
            f"{messaggio_attuale}\n\n"
            "Scrivi SOLO il testo del nuovo messaggio, senza intestazioni o spiegazioni. Max 300 caratteri."
        )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 400,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    risposta = _chiama_api("rigenera_messaggio_outreach", payload)
    return risposta.content[0].text.strip()


def rigenera_messaggio_followup(candidato: dict, messaggio_attuale: str, istruzioni: str = "") -> str:
    """Rigenera o riscrive un messaggio di follow-up."""
    messaggio_attuale = clean_text(messaggio_attuale)
    istruzioni        = clean_text(istruzioni)

    contesto = (
        f"Candidato: {candidato.get('nome','')} {candidato.get('cognome','')}\n"
        f"Ruolo: {candidato.get('ruolo_attuale','N/D')}\n"
        f"Azienda: {candidato.get('azienda','N/D')}\n"
        f"Stato nel processo: {candidato.get('stato','N/D')}"
    )

    if istruzioni:
        prompt = (
            "Sei un recruiter esperto. Riscrivi questo messaggio di follow-up LinkedIn\n"
            f"seguendo queste istruzioni: {istruzioni}\n\n"
            "MESSAGGIO ATTUALE:\n"
            f"{messaggio_attuale}\n\n"
            "CONTESTO CANDIDATO:\n"
            f"{contesto}\n\n"
            "Scrivi SOLO il testo del messaggio, senza intestazioni. Max 300 caratteri."
        )
    else:
        prompt = (
            "Sei un recruiter esperto. Genera una NUOVA variante del messaggio di follow-up\n"
            "LinkedIn, diversa dalla precedente, per questo candidato.\n\n"
            "CONTESTO CANDIDATO:\n"
            f"{contesto}\n\n"
            "VERSIONE PRECEDENTE (da cui differenziarti):\n"
            f"{messaggio_attuale}\n\n"
            "Scrivi SOLO il testo del nuovo messaggio, senza intestazioni. Max 300 caratteri."
        )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 400,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    risposta = _chiama_api("rigenera_messaggio_followup", payload)
    return risposta.content[0].text.strip()


def genera_messaggio_followup(candidato: dict) -> str:
    """Genera un messaggio di follow-up personalizzato per un candidato."""
    prompt = (
        "Sei un recruiter esperto. Scrivi un breve messaggio di follow-up LinkedIn per questo candidato.\n\n"
        f"Candidato: {candidato['nome']} {candidato['cognome']}\n"
        f"Ruolo attuale: {candidato.get('ruolo_attuale', 'N/D')}\n"
        f"Azienda: {candidato.get('azienda', 'N/D')}\n"
        f"Stato nel processo: {candidato.get('stato', 'N/D')}\n"
        f"Note: {candidato.get('note', 'nessuna')}\n\n"
        "Scrivi SOLO il testo del messaggio, senza intestazioni o spiegazioni.\n"
        "Tono professionale e cordiale. Max 300 caratteri."
    )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 400,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    risposta = _chiama_api("genera_messaggio_followup", payload)
    return risposta.content[0].text.strip()


def genera_prompt_immagine(testo_post: str, tema: str, tono: str, prompt_custom: str = "") -> str:
    """Usa Claude per costruire un prompt ottimizzato per Pollinations/FLUX."""
    testo_post    = clean_text(testo_post)
    prompt_custom = clean_text(prompt_custom)
    istruzioni_custom = f"\nModifica richiesta dall'utente: {prompt_custom}" if prompt_custom else ""

    prompt = (
        "Sei un esperto di prompt engineering per generatori di immagini AI.\n"
        "Crea un prompt in inglese per generare un'immagine professionale da usare come visual su LinkedIn.\n\n"
        f"TEMA DEL POST: {tema}\n"
        f"TONO: {tono}\n"
        "TESTO DEL POST (riferimento):\n"
        f"{testo_post[:400]}{istruzioni_custom}\n\n"
        "Il prompt deve descrivere un'immagine:\n"
        "- Professionale, moderna, adatta a LinkedIn\n"
        "- Stile fotografico o illustrativo high-end\n"
        "- Colori prevalenti: blu scuro e azzurro professionale\n"
        "- NO testo nell'immagine\n"
        "- NO persone riconoscibili\n"
        "- Concettuale, evocativa del tema\n\n"
        "Rispondi SOLO con il prompt in inglese, max 200 caratteri, senza virgolette."
    )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 300,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    risposta = _chiama_api("genera_prompt_immagine", payload)
    return risposta.content[0].text.strip()


_OBIETTIVI_LINKEDIN = {
    "candidati": "Attirare candidati qualificati verso nuove opportunità di carriera",
    "insight":   "Condividere un insight professionale originale che stimoli la riflessione",
    "successo":  "Raccontare un caso di successo concreto con dettagli e risultati misurabili",
    "educare":   "Educare il pubblico su un tema rilevante con valore pratico immediato",
    "autorita":  "Costruire autorevolezza nel settore con una posizione chiara e distintiva",
}


def genera_contenuti_linkedin(
    tema: str,
    obiettivo: str,
    contesto: str,
    profilo_voce: dict,
) -> dict:
    """
    Genera 3 varianti di post LinkedIn in base al profilo voce dell'autore.

    profilo_voce: dict con chiavi nome, bio_breve, tono_prevalente, settore
    obiettivo: una delle chiavi in _OBIETTIVI_LINKEDIN
    """
    nome    = (profilo_voce or {}).get("nome") or "Professionista"
    bio     = (profilo_voce or {}).get("bio_breve") or ""
    tono    = (profilo_voce or {}).get("tono_prevalente") or "professionale e diretto"
    settore = (profilo_voce or {}).get("settore") or ""

    desc_obiettivo = _OBIETTIVI_LINKEDIN.get(obiettivo, obiettivo or "condividere valore")

    parti = [f"Sei {nome}."]
    if bio:
        parti.append(bio)
    if settore:
        parti.append(f"Lavori nel settore: {settore}.")
    parti.append(f"Il tuo tono di scrittura su LinkedIn è: {tono}.")
    parti.append("")
    parti.append(f"Obiettivo del post: {desc_obiettivo}.")
    parti.append(f"Tema: {tema}.")
    if contesto:
        parti.append(f"Contesto aggiuntivo: {contesto}.")
    parti.append("")
    parti.append("Scrivi 3 varianti di post LinkedIn, ognuna diversa per angolazione e struttura.")
    parti.append("Ogni post deve:")
    parti.append("- Aprire con un hook forte che ferma lo scroll (prima riga)")
    parti.append("- Essere tra 150 e 300 parole")
    parti.append("- Usare emoji con moderazione (max 3-4)")
    parti.append("- Terminare con 3-5 hashtag pertinenti")
    parti.append("- Essere scritto in prima persona, nello stesso tono e voce dell'autore")
    parti.append("")
    parti.append("Rispondi ESCLUSIVAMENTE con questo JSON valido (senza markdown, senza backtick):")
    parti.append("{")
    parti.append('  "variante_1": "<testo completo, a capo come \\n>",')
    parti.append('  "variante_2": "<testo completo, a capo come \\n>",')
    parti.append('  "variante_3": "<testo completo, a capo come \\n>"')
    parti.append("}")

    prompt = "\n".join(parti)
    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 2500,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("genera_contenuti_linkedin", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        return json.loads(testo)
    except Exception as e:
        logger.error("[AI] genera_contenuti_linkedin fallita: %s", e)
        raise


def analizza_profilo_voce(dati_proxycurl: dict, nome: str) -> dict:
    """
    Dato un profilo Proxycurl, chiede a Claude di estrarre:
    - tono_prevalente (come scrive questa persona)
    - settore di riferimento
    - bio_breve (2-3 righe in prima persona)
    Restituisce un dict con queste 3 chiavi.
    """
    from proxycurl_helpers import estrai_testo_proxycurl
    testo_profilo = estrai_testo_proxycurl(dati_proxycurl)
    if not testo_profilo:
        return {"tono_prevalente": "", "settore": "", "bio_breve": ""}

    prompt = (
        f"Analizza il seguente profilo LinkedIn di {nome} e rispondi in JSON.\n\n"
        f"PROFILO:\n{testo_profilo[:2000]}\n\n"
        "Restituisci ESCLUSIVAMENTE questo JSON (no markdown, no backtick):\n"
        "{\n"
        '  "tono_prevalente": "<3-6 aggettivi che descrivono il suo stile di comunicazione>",\n'
        '  "settore": "<settore professionale principale in 3-5 parole>",\n'
        '  "bio_breve": "<2-3 frasi in prima persona che descrivono chi è e cosa fa>"\n'
        "}"
    )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 500,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("analizza_profilo_voce", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        return json.loads(testo)
    except Exception as e:
        logger.error("[AI] analizza_profilo_voce fallita: %s", e)
        return {"tono_prevalente": "", "settore": "", "bio_breve": ""}


def genera_piano_editoriale(analisi: dict, settimane: int = 4, post_settimana: int = 3) -> list:
    """
    Genera il piano editoriale personalizzato basato sull'analisi del profilo.
    Restituisce lista di post pianificati con tema, formato, hook, obiettivo.
    """
    nome = analisi.get('nome', '') or ''
    settore = analisi.get('settore', '') or ''
    headline = analisi.get('headline_attuale', '') or ''
    punti_forza = analisi.get('punti_forza', [])
    keyword = analisi.get('keyword_mancanti', [])
    analisi_contenuti = analisi.get('analisi_contenuti', {}) or {}

    totale_post = settimane * post_settimana

    pf_str = ', '.join(punti_forza) if isinstance(punti_forza, list) else str(punti_forza)
    kw_str = ', '.join(keyword) if isinstance(keyword, list) else str(keyword)
    val_str = analisi_contenuti.get('valutazione', 'Nessuna analisi disponibile') if isinstance(analisi_contenuti, dict) else str(analisi_contenuti)

    prompt = f"""Sei un esperto di content marketing LinkedIn con profonda conoscenza dell'algoritmo.

PROFILO:
Nome: {nome}
Settore: {settore}
Headline: {headline}
Punti di forza: {pf_str}
Keyword strategiche: {kw_str}
Analisi contenuti attuali: {val_str}

PIANO RICHIESTO: {totale_post} post in {settimane} settimane ({post_settimana} post/settimana)

LINEE GUIDA ALGORITMO LINKEDIN DA RISPETTARE:
- Caroselli e documenti PDF hanno il maggiore organic reach
- I video nativi (non YouTube) ottengono 5x piu reach dei link esterni
- I sondaggi generano alto engagement ma non devono essere usati piu di 1 volta ogni 2 settimane
- Post solo testo con hook forte nelle prime 2 righe performano meglio dei post con link esterni
- Mai inserire link nel testo del post — mettili sempre nel primo commento
- Rispondere ai commenti nelle prime 2 ore e fondamentale per l'algoritmo
- Mix ottimale: 30% caroselli, 25% testo, 20% documenti, 15% video, 10% sondaggi
- Alternare contenuti di autorevolezza (35%), visibilita personale (25%), engagement (20%), conversione (20%)
- Pubblicare martedi/mercoledi/giovedi tra 8-9, 12-13, 17-18

Genera SOLO un JSON array con {totale_post} oggetti, uno per post:
[
  {{
    "settimana": 1,
    "giorno": "martedi|mercoledi|giovedi",
    "formato": "carosello|post_testo|documento_pdf|video_nativo|sondaggio",
    "obiettivo": "autorevolezza|visibilita|engagement|conversione",
    "tema": "titolo breve del tema (max 60 caratteri)",
    "hook": "prime 2 righe del post — devono fermare lo scroll (max 120 caratteri)",
    "perche": "1 riga che spiega perche questo post funzionera con l'algoritmo",
    "emoji": "1 emoji che rappresenta il tema"
  }}
]

Il piano deve essere coerente con il settore {settore} e costruire progressivamente l'autorevolezza del profilo.
Solo JSON valido, nessun testo aggiuntivo."""

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 3000,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("genera_piano_editoriale", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        return json.loads(testo)
    except Exception as e:
        logger.error("[AI] genera_piano_editoriale fallita: %s", e)
        raise


def genera_post_da_piano(post_info: dict, profilo_info: dict) -> str:
    """
    Genera il testo completo di un post LinkedIn dal piano editoriale.
    post_info: dict con formato, tema, hook, obiettivo
    profilo_info: dict con nome, settore, headline, tono
    """
    formato = post_info.get('formato', 'post_testo')
    tema = post_info.get('tema', '')
    hook = post_info.get('hook_suggerito') or post_info.get('hook', '')
    obiettivo = post_info.get('obiettivo', '')
    nome = profilo_info.get('nome', '')
    settore = profilo_info.get('settore', '')
    tono = profilo_info.get('tono_prevalente', 'professionale e diretto')

    istruzioni_formato = {
        'carosello': "Scrivi il testo di accompagnamento per un carosello LinkedIn. "
                     "Indica tra parentesi quadre il contenuto di ogni slide [Slide 1: ...]. "
                     "Il testo deve invitare a scorrere.",
        'post_testo': "Scrivi un post solo testo, con hook forte nelle prime 2 righe. "
                      "Struttura: hook → sviluppo → conclusione con CTA.",
        'documento_pdf': "Scrivi il testo di accompagnamento per un documento PDF da condividere. "
                         "Il testo deve incuriosire e spingere a scaricare/leggere il documento.",
        'video_nativo': "Scrivi il testo di accompagnamento per un video nativo LinkedIn. "
                        "Deve descrivere cosa si vedra nel video e invitare a guardarlo.",
        'sondaggio': "Scrivi la domanda del sondaggio, 3-4 opzioni di risposta tra parentesi quadre, "
                     "e un breve testo introduttivo che stimoli la partecipazione.",
    }

    prompt = f"""Sei {nome}, un professionista nel settore {settore}.
Il tuo tono di scrittura su LinkedIn e: {tono}.

Scrivi un post LinkedIn completo su questo tema:
Tema: {tema}
Hook suggerito: {hook}
Obiettivo: {obiettivo}

{istruzioni_formato.get(formato, istruzioni_formato['post_testo'])}

REGOLE:
- Apri con un hook che ferma lo scroll (usa l'hook suggerito come ispirazione)
- Scrivi in prima persona
- Tra 150 e 300 parole
- Usa emoji con moderazione (max 3-4)
- Termina con 3-5 hashtag pertinenti
- NON inserire link nel testo (vanno nel primo commento)
- Scrivi in italiano

Rispondi SOLO con il testo del post, senza intestazioni o spiegazioni."""

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 1500,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("genera_post_da_piano", payload)
        return risposta.content[0].text.strip()
    except Exception as e:
        logger.error("[AI] genera_post_da_piano fallita: %s", e)
        raise


def analizza_profilo_personale(testo_profilo: str) -> dict:
    """
    Analizza un profilo LinkedIn per personal branding.
    Restituisce punteggio, suggerimenti headline/about, punti di forza,
    aree di miglioramento, keyword mancanti e dati per profilo voce.
    """
    prompt = (
        "Sei un esperto di personal branding LinkedIn per recruiter e HR manager.\n"
        "Analizza il seguente profilo LinkedIn e fornisci suggerimenti concreti.\n\n"
        f"PROFILO:\n{testo_profilo[:3000]}\n\n"
        "Restituisci ESCLUSIVAMENTE questo JSON valido (no markdown, no backtick):\n"
        "{\n"
        '  "punteggio": <numero intero 1-10>,\n'
        '  "punteggio_motivazione": "<2 righe che spiegano il punteggio>",\n'
        '  "headline_attuale": "<headline attuale estratta dal profilo>",\n'
        '  "headline_suggerita": "<versione migliorata, max 120 caratteri>",\n'
        '  "about_attuale": "<testo about/summary attuale del profilo, max 500 caratteri>",\n'
        '  "about_suggerito": "<riscrittura suggerita in prima persona, max 300 caratteri>",\n'
        '  "punti_forza": ["<punto 1>", "<punto 2>", "<punto 3>"],\n'
        '  "aree_miglioramento": ["<suggerimento concreto 1>", "<suggerimento 2>", "<suggerimento 3>"],\n'
        '  "keyword_mancanti": ["<keyword 1>", "<keyword 2>", "<keyword 3>", "<keyword 4>", "<keyword 5>"],\n'
        '  "tono_prevalente": "<3-5 aggettivi che descrivono lo stile di scrittura del profilo>",\n'
        '  "settore": "<settore professionale principale in 3-5 parole>",\n'
        '  "bio_breve": "<2-3 frasi in prima persona per presentarsi, usabili come bio nei post>"\n'
        "}"
    )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 1500,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("analizza_profilo_personale", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        return json.loads(testo)
    except Exception as e:
        logger.error("[AI] analizza_profilo_personale fallita: %s", e)
        raise


def analizza_profilo_completo(dati_profilo: dict, post_linkedin: list) -> dict:
    """
    Analisi completa del profilo LinkedIn + contenuti postati.
    Restituisce JSON strutturato con tutti i campi.
    """
    nome = f"{dati_profilo.get('first_name','')} {dati_profilo.get('last_name','')}".strip()
    headline = dati_profilo.get('headline') or dati_profilo.get('title') or ''
    summary = dati_profilo.get('summary') or dati_profilo.get('about') or ''
    esperienze = (dati_profilo.get('experiences') or dati_profilo.get('experience') or [])[:3]
    skills_raw = dati_profilo.get('skills') or []
    if skills_raw and isinstance(skills_raw[0], dict):
        skills = [s.get('name', '') for s in skills_raw[:10]]
    else:
        skills = [str(s) for s in skills_raw[:10]]

    testo_post = ""
    if post_linkedin:
        testo_post = "\n\n".join([
            f"Post {i+1} ({p.get('like',0)} like, {p.get('commenti',0)} commenti):\n{p.get('testo','')}"
            for i, p in enumerate(post_linkedin[:10])
        ])

    esperienze_str = ', '.join([
        (e.get('title', '') + ' @ ' + (e.get('company', '') or e.get('company_name', '')))
        for e in esperienze if isinstance(e, dict)
    ])

    prompt = f"""Sei un esperto di personal branding LinkedIn per professionisti italiani.

PROFILO DA ANALIZZARE:
Nome: {nome}
Headline attuale: {headline}
About attuale: {summary[:800]}
Esperienze: {esperienze_str}
Skills: {', '.join(skills)}

{"ULTIMI POST PUBBLICATI:" + chr(10) + testo_post if testo_post else "Nessun post disponibile per l'analisi dei contenuti."}

Analizza in modo approfondito e restituisci SOLO un JSON con questa struttura:
{{
    "punteggio": <numero 1-10>,
    "punteggio_motivazione": "<2 righe che spiegano il punteggio>",
    "headline_attuale": "{headline[:120]}",
    "headline_suggerita": "<headline migliorata, max 120 caratteri>",
    "about_attuale": "<prime 200 caratteri dell'about attuale>",
    "about_suggerito": "<riscrittura completa dell'about, max 400 caratteri, tono professionale italiano>",
    "punti_forza": ["<punto 1>", "<punto 2>", "<punto 3>"],
    "aree_miglioramento": [
        {{"priorita": "alta", "area": "<area>", "consiglio": "<azione concreta>"}},
        {{"priorita": "alta", "area": "<area>", "consiglio": "<azione concreta>"}},
        {{"priorita": "media", "area": "<area>", "consiglio": "<azione concreta>"}}
    ],
    "keyword_mancanti": ["<keyword 1>", "<keyword 2>", "<keyword 3>", "<keyword 4>", "<keyword 5>"],
    "analisi_contenuti": {{"valutazione": "<analisi tono e qualita dei post, 2-3 righe>", "frequenza": "<commento sulla frequenza di pubblicazione>", "engagement_medio": "<commento sull'engagement>"}},
    "consigli_contenuti": ["<consiglio concreto 1>", "<consiglio concreto 2>", "<consiglio concreto 3>"],
    "tono_prevalente": "<3-5 aggettivi che descrivono lo stile>",
    "settore": "<settore professionale principale>",
    "bio_breve": "<2-3 frasi in prima persona per presentarsi>"
}}

Solo JSON valido, nessun testo aggiuntivo."""

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 2000,
        "messages":   [{"role": "user", "content": clean_text(prompt)}],
    }
    try:
        risposta = _chiama_api("analizza_profilo_completo", payload)
        testo = risposta.content[0].text.strip()
        if testo.startswith("```"):
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]
        return json.loads(testo)
    except Exception as e:
        logger.error("[AI] analizza_profilo_completo fallita: %s", e)
        raise
