"""
Helper per l'arricchimento profili tramite Proxycurl API.
Usa cache: se i dati hanno meno di 30 giorni non richiama l'API.
"""

import os
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def arricchisci_profilo(linkedin_url: str) -> dict | None:
    """
    Recupera i dati arricchiti di un profilo LinkedIn tramite Proxycurl.
    Restituisce il JSON completo o None in caso di errore / chiave mancante.
    """
    api_key = os.environ.get("PROXYCURL_API_KEY")
    if not api_key:
        logger.debug("[Proxycurl] PROXYCURL_API_KEY non configurata — skip arricchimento")
        return None
    if not linkedin_url or "linkedin.com/in/" not in linkedin_url:
        logger.debug("[Proxycurl] URL non valido: %s", linkedin_url)
        return None

    try:
        resp = requests.get(
            "https://enrichlayer.com/api/v2/profile",
            params={
                "profile_url": linkedin_url,
                "use_cache": "if-present",
                "fallback_to_cache": "on-error",
                "activities": "include",
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        if resp.status_code == 200:
            dati = resp.json()
            dati["_fetched_at"] = datetime.now().isoformat()
            logger.info("[Proxycurl] Profilo arricchito OK: %s", linkedin_url)
            return dati
        logger.warning("[Proxycurl] HTTP %s per %s: %s", resp.status_code, linkedin_url, resp.text[:200])
        return None
    except requests.exceptions.Timeout:
        logger.error("[Proxycurl] Timeout per %s", linkedin_url)
        return None
    except Exception as e:
        logger.error("[Proxycurl] Errore per %s: %s", linkedin_url, e)
        return None


def is_cache_valida(dati_prx: dict, max_giorni: int = 30) -> bool:
    """Restituisce True se i dati Proxycurl sono stati recuperati negli ultimi max_giorni."""
    fa = dati_prx.get("_fetched_at")
    if not fa:
        return False
    try:
        fetched = datetime.fromisoformat(fa)
        return datetime.now() - fetched < timedelta(days=max_giorni)
    except Exception:
        return False


def estrai_testo_proxycurl(dati_prx: dict) -> str:
    """
    Estrae i campi rilevanti da Proxycurl e li formatta come testo
    leggibile da Claude per l'analisi arricchita.
    """
    if not dati_prx:
        return ""
    parti = []

    follower = dati_prx.get("follower_count")
    if follower:
        parti.append(f"Follower LinkedIn: {follower:,}")

    connections = dati_prx.get("connections")
    if connections:
        parti.append(f"Connessioni LinkedIn: {connections}")

    # Certificazioni
    certs = dati_prx.get("certifications") or []
    if certs:
        nomi = [c.get("name", "") for c in certs[:5] if c.get("name")]
        if nomi:
            parti.append(f"Certificazioni: {', '.join(nomi)}")

    # Volontariato
    vols = dati_prx.get("volunteer_work") or []
    if vols:
        cause = [v.get("cause", "") or v.get("organization", "") for v in vols[:3] if v]
        cause = [c for c in cause if c]
        if cause:
            parti.append(f"Volontariato: {', '.join(cause)}")

    # Raccomandazioni
    recs = dati_prx.get("recommendations") or []
    if recs:
        parti.append(f"Raccomandazioni ricevute: {len(recs)}")

    # Pubblicazioni
    pubs = dati_prx.get("accomplishment_publications") or []
    if pubs:
        parti.append(f"Pubblicazioni: {len(pubs)}")

    # Premi
    awards = dati_prx.get("accomplishment_honors_awards") or []
    if awards:
        parti.append(f"Premi/riconoscimenti: {len(awards)}")

    # Attività recenti (post)
    activities = dati_prx.get("activities") or []
    if activities:
        post_titoli = [a.get("title", "") for a in activities[:5] if a.get("title")]
        if post_titoli:
            parti.append("Ultimi post pubblicati:\n" + "\n".join(f"  • {t[:100]}" for t in post_titoli))

    # Data aggiornamento profilo
    last_updated = dati_prx.get("last_updated")
    if last_updated:
        parti.append(f"Profilo aggiornato: {str(last_updated)[:10]}")

    return "\n".join(parti) if parti else "Dati arricchiti non disponibili"
