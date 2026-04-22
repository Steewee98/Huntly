"""
Adapter LinkedIn per Huntly.
Cerca profili tramite Apify harvestapi~linkedin-profile-search.
"""
import json
import logging
import os
import time

import requests

from sources.utils import normalizza_citta, normalizza_profilo_linkedin

log = logging.getLogger(__name__)

APIFY_ACTOR = "harvestapi~linkedin-profile-search"
APIFY_BASE  = "https://api.apify.com/v2"
TIMEOUT_MAX = 200   # secondi — LinkedIn è la sorgente principale, timeout più lungo


def cerca_linkedin(ruolo: str, citta: str = "", paese: str = "", azienda: str = "",
                   parole_chiave: str = "", num_pagine: int = 1, start_page: int = 1) -> tuple:
    """
    Cerca profili LinkedIn tramite Apify.

    Flusso:
      STEP 1 — POST /acts/{actor}/runs  → avvia run
      STEP 2 — GET  /actor-runs/{id}    → poll ogni 5s fino a TIMEOUT_MAX
      STEP 3 — GET  /datasets/{id}/items → recupera risultati

    Restituisce (lista_profili_normalizzati, errore_o_None).
    Ogni profilo ha source='linkedin'.
    """
    api_key = os.environ.get("APIFY_API_KEY", "")
    if not api_key:
        return None, "APIFY_API_KEY non configurata"

    run_input = {
        "takePages": num_pagine,
        "startPage": max(1, start_page),
        "maxItems":  10,
    }

    # Titoli di lavoro
    titoli = [ruolo] if ruolo else []
    if titoli:
        run_input["currentJobTitles"] = titoli

    # Keywords combinate
    kw_parts = []
    if titoli:
        kw_parts.append(" OR ".join(f'"{t}"' for t in titoli[:3]))
    if parole_chiave:
        kw_parts.append(parole_chiave)
    if kw_parts:
        run_input["keywords"] = " ".join(kw_parts)

    # Location
    if citta or paese:
        citta_norm = normalizza_citta(citta) if citta else ""
        run_input["locations"] = [", ".join(filter(None, [citta_norm, paese]))] if paese else [citta_norm]
    else:
        run_input["locations"] = ["Italy"]

    if azienda:
        run_input["currentCompanies"] = [azienda]

    log.info("[linkedin] INPUT: %s", json.dumps(run_input, ensure_ascii=False))

    # ── STEP 1: Avvia run ─────────────────────────────────────────────────
    try:
        resp = requests.post(
            f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs",
            json=run_input,
            params={"token": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        run_data   = resp.json()["data"]
        run_id     = run_data["id"]
        dataset_id = run_data["defaultDatasetId"]
    except requests.exceptions.HTTPError:
        return None, f"LinkedIn avvio errore HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return None, f"LinkedIn avvio errore: {e}"

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
                return None, f"LinkedIn run terminato con stato: {status}"
        except requests.exceptions.RequestException:
            pass
    else:
        return None, f"LinkedIn timeout: ricerca ha impiegato più di {TIMEOUT_MAX}s"

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

        profili = [normalizza_profilo_linkedin(item) for item in items if isinstance(item, dict)]
        log.info("[linkedin] %d profili trovati", len(profili))
        return profili, None

    except requests.exceptions.HTTPError:
        return None, f"LinkedIn fetch errore HTTP {ir.status_code}: {ir.text[:200]}"
    except requests.exceptions.RequestException as e:
        return None, f"LinkedIn fetch errore: {e}"
