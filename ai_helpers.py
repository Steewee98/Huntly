"""
Helper per le chiamate all'API Anthropic Claude.
Contiene tutte le funzioni AI usate dai vari moduli dell'app.
"""

import anthropic
import os
import json
import re
import logging

# Model ID corretto per Claude Sonnet 4.6
CLAUDE_MODEL = "claude-sonnet-4-6"

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


def analizza_profilo_linkedin(testo_profilo: str, tipo_profilo: str, impostazioni: dict = None) -> dict:
    """
    Analizza un profilo LinkedIn e restituisce valutazione strutturata.
    tipo_profilo: 'A' = Senior, 'B' = Under 35
    """
    testo_profilo = clean_text(testo_profilo)

    if impostazioni:
        if tipo_profilo == "A":
            descrizione_profilo = (
                f"Profilo A (Senior): età tra {impostazioni.get('eta_min', 40)} e "
                f"{impostazioni.get('eta_max', 65)} anni, almeno "
                f"{impostazioni.get('anni_esperienza_min', 5)} anni di esperienza nel settore. "
                f"Settori di provenienza accettati: {impostazioni.get('settori', 'consulenza, bancario, finanziario')}. "
                f"Ruoli target: {impostazioni.get('ruoli_target', '')}. "
                f"Segnali positivi (favoriscono la valutazione): {impostazioni.get('keyword_positive', '')}. "
                f"Segnali negativi (penalizzano la valutazione): {impostazioni.get('keyword_negative', '')}."
            )
        else:
            descrizione_profilo = (
                f"Profilo B (Under 35): età tra {impostazioni.get('eta_min', 22)} e "
                f"{impostazioni.get('eta_max', 35)} anni, almeno "
                f"{impostazioni.get('anni_esperienza_min', 2)} anni di esperienza bancaria. "
                f"Istituti di provenienza preferiti: {impostazioni.get('istituti', 'banche, assicurazioni, SIM')}. "
                f"Ruoli target: {impostazioni.get('ruoli_target', '')}. "
                f"Segnali positivi (favoriscono la valutazione): {impostazioni.get('keyword_positive', '')}. "
                f"Segnali negativi (penalizzano la valutazione): {impostazioni.get('keyword_negative', '')}."
            )
        p_eta = impostazioni.get('peso_eta', 5)
        p_esp = impostazioni.get('peso_esperienza', 5)
        p_set = impostazioni.get('peso_settore', 5)
        p_ruo = impostazioni.get('peso_ruolo', 5)
        p_kw  = impostazioni.get('peso_keyword', 5)
        istr_punteggio = (
            f"\nPer il punteggio finale (1-10) usa questi pesi (scala 0-10, 0=ignora, 10=determinante):\n"
            f"- Eta nel range target: {p_eta}/10\n"
            f"- Anni di esperienza: {p_esp}/10\n"
            f"- Settore/istituto di provenienza: {p_set}/10\n"
            f"- Corrispondenza ruolo target: {p_ruo}/10\n"
            f"- Parole chiave positive/negative: {p_kw}/10"
        )
    else:
        if tipo_profilo == "A":
            descrizione_profilo = (
                "Profilo A: professionista senior tra 40 e 65 anni, "
                "con esperienza in consulenza, libero professionista o con P.IVA, "
                "orientato all'autonomia e alla gestione clienti."
            )
        else:
            descrizione_profilo = (
                "Profilo B: professionista under 35 con esperienza bancaria, "
                "orientato alla crescita professionale nel settore finanziario."
            )
        istr_punteggio = ""

    prompt = (
        "Sei un esperto recruiter nel settore della consulenza finanziaria e bancaria.\n"
        "Analizza il seguente profilo LinkedIn per valutarne la compatibilita con questo target:\n\n"
        f"{descrizione_profilo}{istr_punteggio}\n\n"
        "PROFILO LINKEDIN:\n"
        f"{testo_profilo}\n\n"
        "Fornisci la tua analisi ESCLUSIVAMENTE nel seguente formato JSON valido, senza testo aggiuntivo:\n"
        "{\n"
        '  "nome_contatto": "<nome e cognome della persona estratto dal testo, o null se non identificabile>",\n'
        '  "ruolo_attuale": "<ruolo/titolo professionale attuale estratto dal testo, o null>",\n'
        '  "azienda": "<nome dell\'azienda attuale estratto dal testo, o null>",\n'
        '  "anni_esperienza": <numero intero degli anni totali di esperienza professionale stimati dal testo, o null>,\n'
        '  "punteggio": <numero da 1 a 10>,\n'
        '  "analisi_percorso": "<analisi dettagliata del percorso professionale in 3-4 frasi>",\n'
        '  "spunti_contatto": [\n'
        '    "<spunto personalizzato 1 per il primo contatto>",\n'
        '    "<spunto personalizzato 2 per il primo contatto>",\n'
        '    "<spunto personalizzato 3 per il primo contatto>"\n'
        '  ],\n'
        '  "messaggio_outreach": "<bozza completa del messaggio di outreach personalizzato su LinkedIn, tono professionale ma umano, max 300 caratteri>"\n'
        "}"
    )

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


def genera_contenuti_linkedin(tema: str, tono: str, profilo: str) -> dict:
    """Genera 3 varianti di post LinkedIn."""
    descrizioni_tono = {
        "professionale": "formale, autorevole, basato su dati e risultati concreti",
        "ispirazionale": "motivante, emotivo, con storie e metafore, che spinge all'azione",
        "educativo":     "informativo, chiaro, che insegna qualcosa di valore al lettore",
    }
    descrizioni_profilo = {
        "Salvatore Sabia": (
            "Salvatore Sabia, imprenditore nel settore della consulenza finanziaria, "
            "con anni di esperienza nella selezione di professionisti del mondo bancario."
        ),
        "Assistente Recrutatrice": (
            "Assistente recrutatrice specializzata nel settore bancario-finanziario, "
            "che aiuta professionisti a trovare nuove opportunita di crescita."
        ),
    }

    prompt = (
        "Sei un esperto di content marketing LinkedIn nel settore finanziario.\n\n"
        "Scrivi 3 varianti di post LinkedIn con queste caratteristiche:\n"
        f"- Tema: {tema}\n"
        f"- Tono: {descrizioni_tono.get(tono, tono)}\n"
        f"- Scritto in prima persona da: {descrizioni_profilo.get(profilo, profilo)}\n\n"
        "Ogni post deve avere:\n"
        "1. Un HOOK d'apertura forte (prima riga che cattura l'attenzione)\n"
        "2. Un CORPO con il messaggio principale\n"
        "3. Una CALL TO ACTION finale\n\n"
        "Fornisci il risultato ESCLUSIVAMENTE in questo formato JSON valido:\n"
        "{\n"
        '  "variante_1": "<testo completo del post 1, con a capo come \\n>",\n'
        '  "variante_2": "<testo completo del post 2, con a capo come \\n>",\n'
        '  "variante_3": "<testo completo del post 3, con a capo come \\n>"\n'
        "}"
    )

    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 2000,
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
