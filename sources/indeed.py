"""
Adapter Indeed Italy per Huntly.
Cerca job listings tramite Apify misceres/indeed-scraper.
Converte ogni listing in un profilo sintetico: l'azienda che cerca
quella figura diventa un lead da contattare.
"""
import json
import logging
import os
import time

import requests

from sources.utils import normalizza_profilo_indeed

log = logging.getLogger(__name__)

INDEED_ACTOR = "misceres~indeed-scraper"
APIFY_BASE   = "https://api.apify.com/v2"
TIMEOUT_MAX  = 140   # secondi


def cerca_indeed(ruolo: str, citta: str = "") -> tuple:
    """
    Cerca job listings su Indeed Italy per il ruolo indicato.
    Converte ogni listing in un profilo sintetico (lead aziendale).

    Restituisce (lista_profili_normalizzati, errore_o_None).
    Ogni profilo ha source='indeed'.
    """
    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        return None, "APIFY_API_KEY non configurata"

    # Indeed scraper input — usa position + location per l'Italia
    location = citta.strip() if citta else "Italia"
    run_input = {
        "position":           ruolo or "consulente",
        "location":           location,
        "maxItemsPerSearch":  10,
        "country":            "IT",
    }

    log.info("[indeed] INPUT: %s", json.dumps(run_input, ensure_ascii=False))

    # ── STEP 1: Avvia run ─────────────────────────────────────────────────
    try:
        resp = requests.post(
            f"{APIFY_BASE}/acts/{INDEED_ACTOR}/runs",
            json=run_input,
            params={"token": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        run_data   = resp.json()["data"]
        run_id     = run_data["id"]
        dataset_id = run_data["defaultDatasetId"]
    except requests.exceptions.HTTPError:
        return None, f"Indeed avvio errore HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return None, f"Indeed avvio errore: {e}"

    # ── STEP 2: Poll ogni 5s ──────────────────────────────────────────────
    elapsed = 0
    while elapsed < TIMEOUT_MAX:
        time.sleep(5)
        elapsed += 5
        try:
            sr = requests.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                params={"token": api_key},
                timeout=10,
            )
            sr.raise_for_status()
            run_status = sr.json()["data"]
            status     = run_status.get("status", "")
            if status == "SUCCEEDED":
                dataset_id = run_status.get("defaultDatasetId", dataset_id)
                break
            elif status in ("FAILED", "TIMED-OUT", "ABORTED"):
                return None, f"Indeed run terminato con stato: {status}"
        except requests.exceptions.RequestException:
            pass
    else:
        return None, f"Indeed timeout: ricerca ha impiegato più di {TIMEOUT_MAX}s"

    # ── STEP 3: Recupera risultati ────────────────────────────────────────
    try:
        ir = requests.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"token": api_key, "limit": 10},
            timeout=30,
        )
        ir.raise_for_status()
        items = ir.json()
        if isinstance(items, dict):
            items = items.get("items", [])
        if not isinstance(items, list):
            items = []

        profili = [normalizza_profilo_indeed(item) for item in items if isinstance(item, dict)]
        # Filtra listing senza azienda e senza titolo (dati incompleti)
        profili = [p for p in profili if p["azienda"] != "Azienda non specificata" or p["ruolo"]]
        log.info("[indeed] %d job listings trovati", len(profili))
        return profili, None

    except requests.exceptions.HTTPError:
        return None, f"Indeed fetch errore HTTP {ir.status_code}: {ir.text[:200]}"
    except requests.exceptions.RequestException as e:
        return None, f"Indeed fetch errore: {e}"
