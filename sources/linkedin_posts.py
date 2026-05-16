"""
Scraper post LinkedIn tramite Apify.
Recupera gli ultimi post pubblici di un profilo.
"""
import os, time, requests, logging

log = logging.getLogger(__name__)
APIFY_KEY = os.getenv('APIFY_API_KEY')


def scrapa_post_linkedin(linkedin_url: str, max_post: int = 15) -> list:
    """
    Recupera gli ultimi post pubblici di un profilo LinkedIn.
    Restituisce lista di dict con: testo, data, like, commenti, tipo
    """
    if not APIFY_KEY:
        log.warning("APIFY_API_KEY non configurata — skip scraping post")
        return []

    actor = "curious_coder~linkedin-profile-scraper"
    url = f"https://api.apify.com/v2/acts/{actor}/runs?token={APIFY_KEY}"

    payload = {
        "profileUrls": [linkedin_url],
        "maxPosts": max_post
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 201:
            log.warning("Actor %s errore %d", actor, r.status_code)
            return []

        run_id = r.json()["data"]["id"]

        for _ in range(24):
            time.sleep(5)
            stato = requests.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_KEY}"
            ).json()["data"]["status"]
            if stato == "SUCCEEDED":
                break
            if stato in ("FAILED", "ABORTED", "TIMED-OUT"):
                log.warning("Run %s terminato con stato %s", run_id, stato)
                return []

        items = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items?token={APIFY_KEY}"
        ).json()

        post = []
        for item in items:
            testo = item.get("text") or item.get("content") or ""
            if not testo:
                continue
            post.append({
                "testo": testo[:500],
                "data": item.get("postedAt") or item.get("date") or "",
                "like": item.get("likesCount") or item.get("likes") or 0,
                "commenti": item.get("commentsCount") or item.get("comments") or 0,
                "tipo": item.get("type") or "post"
            })

        return post[:max_post]

    except Exception as e:
        log.error("Errore scraping post LinkedIn: %s", e)
        return []
