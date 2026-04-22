"""
Orchestratore multi-source per Huntly.
Lancia LinkedIn, Indeed e InfoJobs in parallelo tramite ThreadPoolExecutor.
Se una sorgente fallisce, le altre continuano — nessun blocco totale.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError

from sources.linkedin import cerca_linkedin
from sources.indeed   import cerca_indeed
from sources.infojobs import cerca_infojobs

log = logging.getLogger(__name__)

# Timeout globale (secondi): un po' sopra il timeout più lungo delle singole sorgenti
_TIMEOUT_GLOBALE = 215


def cerca_multi_source(ruolo: str, citta: str = "", paese: str = "", azienda: str = "",
                        parole_chiave: str = "", num_pagine: int = 1,
                        start_page: int = 1) -> dict:
    """
    Lancia LinkedIn, Indeed e InfoJobs in parallelo.

    Restituisce un dict con:
      - profili:        lista di tutti i profili aggregati (ognuno ha campo 'source')
      - errori:         {source: messaggio_errore} per le sorgenti fallite
      - source_summary: stringa "LinkedIn: N | Indeed: M | Infojobs: K"
      - conteggi:       {source: n_profili} per ogni sorgente
    """
    # Definisce le tre sorgenti come callable senza argomenti
    sorgenti = {
        'linkedin': lambda: cerca_linkedin(
            ruolo, citta, paese, azienda, parole_chiave, num_pagine, start_page
        ),
        'indeed':   lambda: cerca_indeed(ruolo, citta),
        'infojobs': lambda: cerca_infojobs(ruolo, citta),
    }

    tutti_profili = []
    errori        = {}
    conteggi      = {src: 0 for src in sorgenti}

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_source = {
            executor.submit(fn): src
            for src, fn in sorgenti.items()
        }

        try:
            for future in as_completed(future_to_source, timeout=_TIMEOUT_GLOBALE):
                src = future_to_source[future]
                try:
                    profili, errore = future.result()
                    if errore:
                        log.warning("[multi_source] %s errore: %s", src, errore)
                        errori[src] = errore
                    else:
                        profili = profili or []
                        tutti_profili.extend(profili)
                        conteggi[src] = len(profili)
                        log.info("[multi_source] %s: %d profili", src, len(profili))
                except Exception as e:
                    log.error("[multi_source] %s eccezione: %s", src, e, exc_info=True)
                    errori[src] = str(e)

        except FutureTimeoutError:
            log.warning("[multi_source] Timeout globale %ds raggiunto", _TIMEOUT_GLOBALE)
            for future, src in future_to_source.items():
                if not future.done():
                    errori[src] = f"Timeout globale {_TIMEOUT_GLOBALE}s"
                    log.warning("[multi_source] %s non completato in tempo", src)
                elif src not in errori and src not in {k for k, v in conteggi.items() if v > 0}:
                    # Future completato ma non ancora processato
                    try:
                        profili, errore = future.result()
                        if not errore:
                            profili = profili or []
                            tutti_profili.extend(profili)
                            conteggi[src] = len(profili)
                    except Exception:
                        pass

    # Genera source_summary leggibile
    parti = [f"{src.capitalize()}: {n}" for src, n in conteggi.items() if n > 0]
    source_summary = " | ".join(parti) if parti else "Nessun risultato"

    log.info("[multi_source] totale=%d conteggi=%s errori=%s",
             len(tutti_profili), conteggi, list(errori.keys()))

    return {
        'profili':        tutti_profili,
        'errori':         errori,
        'source_summary': source_summary,
        'conteggi':       conteggi,
    }
