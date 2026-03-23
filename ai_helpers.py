"""
Helper per le chiamate all'API Anthropic Claude.
Contiene tutte le funzioni AI usate dai vari moduli dell'app.
"""

import anthropic
import os
import json


def get_client():
    """Crea e restituisce il client Anthropic."""
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def analizza_profilo_linkedin(testo_profilo: str, tipo_profilo: str, impostazioni: dict = None) -> dict:
    """
    Analizza un profilo LinkedIn e restituisce valutazione strutturata.

    tipo_profilo: 'A' = Senior, 'B' = Under 35
    impostazioni: dict con i parametri configurati nella pagina Impostazioni (opzionale)
    """
    client = get_client()

    if impostazioni:
        # Usa i parametri personalizzati dell'utente
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

        p_eta  = impostazioni.get('peso_eta', 5)
        p_esp  = impostazioni.get('peso_esperienza', 5)
        p_set  = impostazioni.get('peso_settore', 5)
        p_ruo  = impostazioni.get('peso_ruolo', 5)
        p_kw   = impostazioni.get('peso_keyword', 5)
        istr_punteggio = (
            f"\nPer il punteggio finale (1-10) usa questi pesi (scala 0-10, 0=ignora, 10=determinante):\n"
            f"- Età nel range target: {p_eta}/10\n"
            f"- Anni di esperienza: {p_esp}/10\n"
            f"- Settore/istituto di provenienza: {p_set}/10\n"
            f"- Corrispondenza ruolo target: {p_ruo}/10\n"
            f"- Parole chiave positive/negative: {p_kw}/10"
        )
    else:
        # Valori di default
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

    prompt = f"""Sei un esperto recruiter nel settore della consulenza finanziaria e bancaria.
Analizza il seguente profilo LinkedIn per valutarne la compatibilità con questo target:

{descrizione_profilo}{istr_punteggio}

PROFILO LINKEDIN:
{testo_profilo}

Fornisci la tua analisi ESCLUSIVAMENTE nel seguente formato JSON valido, senza testo aggiuntivo:
{{
  "nome_contatto": "<nome e cognome della persona estratto dal testo, o null se non identificabile>",
  "ruolo_attuale": "<ruolo/titolo professionale attuale estratto dal testo, o null>",
  "azienda": "<nome dell'azienda attuale estratto dal testo, o null>",
  "anni_esperienza": <numero intero degli anni totali di esperienza professionale stimati dal testo, o null>,
  "punteggio": <numero da 1 a 10>,
  "analisi_percorso": "<analisi dettagliata del percorso professionale in 3-4 frasi>",
  "spunti_contatto": [
    "<spunto personalizzato 1 per il primo contatto>",
    "<spunto personalizzato 2 per il primo contatto>",
    "<spunto personalizzato 3 per il primo contatto>"
  ],
  "messaggio_outreach": "<bozza completa del messaggio di outreach personalizzato su LinkedIn, tono professionale ma umano, max 300 caratteri>"
}}"""

    risposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    testo = risposta.content[0].text.strip()
    # Rimuovi eventuali backtick markdown
    if testo.startswith("```"):
        testo = testo.split("```")[1]
        if testo.startswith("json"):
            testo = testo[4:]
    return json.loads(testo)


def rigenera_messaggio_outreach(testo_profilo: str, messaggio_attuale: str, istruzioni: str = "") -> str:
    """
    Rigenera il messaggio di outreach.
    Se vengono fornite istruzioni personalizzate, le usa per riscrivere il messaggio attuale.
    Altrimenti genera una nuova variante partendo dal profilo.
    """
    client = get_client()

    if istruzioni:
        prompt = f"""Sei un recruiter esperto. Riscrivi il seguente messaggio di outreach LinkedIn
seguendo queste istruzioni: {istruzioni}

MESSAGGIO ATTUALE:
{messaggio_attuale}

PROFILO DEL CANDIDATO (contesto):
{testo_profilo[:500]}

Riscrivi SOLO il testo del messaggio, senza intestazioni o spiegazioni. Max 300 caratteri."""
    else:
        prompt = f"""Sei un recruiter esperto. Genera una NUOVA variante del messaggio di outreach LinkedIn
per questo candidato. Deve essere diversa dalla versione precedente, mantenendo tono professionale e umano.

PROFILO DEL CANDIDATO:
{testo_profilo[:500]}

VERSIONE PRECEDENTE (da cui differenziarti):
{messaggio_attuale}

Scrivi SOLO il testo del nuovo messaggio, senza intestazioni o spiegazioni. Max 300 caratteri."""

    risposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return risposta.content[0].text.strip()


def rigenera_messaggio_followup(candidato: dict, messaggio_attuale: str, istruzioni: str = "") -> str:
    """
    Rigenera o riscrive un messaggio di follow-up.
    Se istruzioni è vuoto genera una nuova variante, altrimenti riscrive seguendo le istruzioni.
    """
    client = get_client()

    contesto = (
        f"Candidato: {candidato.get('nome','')} {candidato.get('cognome','')}\n"
        f"Ruolo: {candidato.get('ruolo_attuale','N/D')}\n"
        f"Azienda: {candidato.get('azienda','N/D')}\n"
        f"Stato nel processo: {candidato.get('stato','N/D')}"
    )

    if istruzioni:
        prompt = f"""Sei un recruiter esperto. Riscrivi questo messaggio di follow-up LinkedIn
seguendo queste istruzioni: {istruzioni}

MESSAGGIO ATTUALE:
{messaggio_attuale}

CONTESTO CANDIDATO:
{contesto}

Scrivi SOLO il testo del messaggio, senza intestazioni. Max 300 caratteri."""
    else:
        prompt = f"""Sei un recruiter esperto. Genera una NUOVA variante del messaggio di follow-up
LinkedIn, diversa dalla precedente, per questo candidato.

CONTESTO CANDIDATO:
{contesto}

VERSIONE PRECEDENTE (da cui differenziarti):
{messaggio_attuale}

Scrivi SOLO il testo del nuovo messaggio, senza intestazioni. Max 300 caratteri."""

    risposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return risposta.content[0].text.strip()


def genera_messaggio_followup(candidato: dict) -> str:
    """Genera un messaggio di follow-up personalizzato per un candidato."""
    client = get_client()

    prompt = f"""Sei un recruiter esperto. Scrivi un breve messaggio di follow-up LinkedIn per questo candidato.

Candidato: {candidato['nome']} {candidato['cognome']}
Ruolo attuale: {candidato.get('ruolo_attuale', 'N/D')}
Azienda: {candidato.get('azienda', 'N/D')}
Stato nel processo: {candidato.get('stato', 'N/D')}
Note: {candidato.get('note', 'nessuna')}

Scrivi SOLO il testo del messaggio, senza intestazioni o spiegazioni.
Tono professionale e cordiale. Max 300 caratteri."""

    risposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    return risposta.content[0].text.strip()


def genera_prompt_immagine(testo_post: str, tema: str, tono: str, prompt_custom: str = "") -> str:
    """
    Usa Claude per costruire un prompt ottimizzato per Pollinations/FLUX
    a partire dal testo del post LinkedIn.
    """
    client = get_client()

    istruzioni_custom = f"\nModifica richiesta dall'utente: {prompt_custom}" if prompt_custom else ""

    prompt = f"""Sei un esperto di prompt engineering per generatori di immagini AI.
Crea un prompt in inglese per generare un'immagine professionale da usare come visual su LinkedIn.

TEMA DEL POST: {tema}
TONO: {tono}
TESTO DEL POST (riferimento):
{testo_post[:400]}{istruzioni_custom}

Il prompt deve descrivere un'immagine:
- Professionale, moderna, adatta a LinkedIn
- Stile fotografico o illustrativo high-end
- Colori prevalenti: blu scuro e azzurro professionale
- NO testo nell'immagine
- NO persone riconoscibili
- Concettuale, evocativa del tema

Rispondi SOLO con il prompt in inglese, max 200 caratteri, senza virgolette."""

    risposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return risposta.content[0].text.strip()


def genera_contenuti_linkedin(tema: str, tono: str, profilo: str) -> dict:
    """
    Genera 3 varianti di post LinkedIn.

    tono: 'professionale' | 'ispirazionale' | 'educativo'
    profilo: 'Salvatore Sabia' | 'Assistente Recrutatrice'
    """
    client = get_client()

    descrizioni_tono = {
        "professionale": "formale, autorevole, basato su dati e risultati concreti",
        "ispirazionale": "motivante, emotivo, con storie e metafore, che spinge all'azione",
        "educativo": "informativo, chiaro, che insegna qualcosa di valore al lettore"
    }

    descrizioni_profilo = {
        "Salvatore Sabia": (
            "Salvatore Sabia, imprenditore nel settore della consulenza finanziaria, "
            "con anni di esperienza nella selezione di professionisti del mondo bancario."
        ),
        "Assistente Recrutatrice": (
            "Assistente recrutatrice specializzata nel settore bancario-finanziario, "
            "che aiuta professionisti a trovare nuove opportunità di crescita."
        )
    }

    prompt = f"""Sei un esperto di content marketing LinkedIn nel settore finanziario.

Scrivi 3 varianti di post LinkedIn con queste caratteristiche:
- Tema: {tema}
- Tono: {descrizioni_tono.get(tono, tono)}
- Scritto in prima persona da: {descrizioni_profilo.get(profilo, profilo)}

Ogni post deve avere:
1. Un HOOK d'apertura forte (prima riga che cattura l'attenzione)
2. Un CORPO con il messaggio principale
3. Una CALL TO ACTION finale

Fornisci il risultato ESCLUSIVAMENTE in questo formato JSON valido:
{{
  "variante_1": "<testo completo del post 1, con a capo come \\n>",
  "variante_2": "<testo completo del post 2, con a capo come \\n>",
  "variante_3": "<testo completo del post 3, con a capo come \\n>"
}}"""

    risposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    testo = risposta.content[0].text.strip()
    if testo.startswith("```"):
        testo = testo.split("```")[1]
        if testo.startswith("json"):
            testo = testo[4:]
    return json.loads(testo)
