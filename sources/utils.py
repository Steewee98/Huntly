"""
Utility condivise per i source adapter di Huntly.
Normalizzazione città, profili, badge sorgente.
"""

# ── Badge UI per ogni sorgente ──────────────────────────────────────────────
SOURCE_BADGES = {
    'linkedin': {'label': 'LinkedIn', 'color': '#0A66C2'},
    'indeed':   {'label': 'Indeed',   'color': '#2164F3'},
    'infojobs': {'label': 'Infojobs', 'color': '#FF6B35'},
}

# ── Normalizzazione città ───────────────────────────────────────────────────
# Apify riconosce il formato completo "Città, Regione, Paese"
_CITTA_NORMALIZE = {
    'roma':     'Rome, Latium, Italy',
    'rome':     'Rome, Latium, Italy',
    'milano':   'Milan, Lombardy, Italy',
    'milan':    'Milan, Lombardy, Italy',
    'torino':   'Turin, Piedmont, Italy',
    'turin':    'Turin, Piedmont, Italy',
    'napoli':   'Naples, Campania, Italy',
    'naples':   'Naples, Campania, Italy',
    'firenze':  'Florence, Tuscany, Italy',
    'florence': 'Florence, Tuscany, Italy',
    'bologna':  'Bologna, Emilia-Romagna, Italy',
    'genova':   'Genoa, Liguria, Italy',
    'genoa':    'Genoa, Liguria, Italy',
    'palermo':  'Palermo, Sicily, Italy',
    'venezia':  'Venice, Veneto, Italy',
    'venice':   'Venice, Veneto, Italy',
    'verona':   'Verona, Veneto, Italy',
    'bari':     'Bari, Apulia, Italy',
    'padova':   'Padua, Veneto, Italy',
    'padua':    'Padua, Veneto, Italy',
}


def normalizza_citta(citta: str) -> str:
    """
    Normalizza il nome città per Apify.
    - Se è nel dizionario → usa il nome completo
    - Se non contiene già 'italy' → aggiunge ', Italy'
    - Se vuota → restituisce 'Italy'
    """
    if not citta:
        return "Italy"
    key = citta.strip().lower()
    if key in _CITTA_NORMALIZE:
        return _CITTA_NORMALIZE[key]
    if "italy" not in key:
        return citta.strip() + ", Italy"
    return citta.strip()


def _str(val) -> str:
    """
    Converte qualsiasi valore in stringa sicura.
    Gestisce i casi in cui Apify restituisce oggetti annidati invece di stringhe.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for key in ("linkedinText", "text", "name", "value", "title"):
            if val.get(key) and isinstance(val[key], str):
                return val[key]
        return ""
    if isinstance(val, list):
        return ", ".join(_str(v) for v in val if v)
    return str(val)


def normalizza_profilo_linkedin(p: dict) -> dict:
    """
    Normalizza un profilo grezzo da Apify harvestapi~linkedin-profile-search.
    Restituisce un dict standard con campo source='linkedin'.
    """
    nome    = _str(p.get("firstName") or p.get("first_name") or "")
    cognome = _str(p.get("lastName")  or p.get("last_name")  or "")
    ruolo   = _str(p.get("headline") or p.get("title") or p.get("occupation") or "")

    azienda = ""
    posizione_corrente = p.get("currentPositions") or p.get("positions") or []
    if posizione_corrente and isinstance(posizione_corrente, list):
        prima = posizione_corrente[0] if isinstance(posizione_corrente[0], dict) else {}
        azienda = _str(prima.get("companyName") or prima.get("company") or "")
        if not ruolo:
            ruolo = _str(prima.get("title") or "")
    if not azienda:
        azienda = _str(p.get("companyName") or p.get("company") or "")

    location = _str(p.get("location") or p.get("geoLocation") or "")
    linkedin  = _str(p.get("linkedinUrl") or p.get("profileUrl") or p.get("url") or "")
    summary   = _str(p.get("summary") or p.get("about") or "")[:200]

    return {
        "nome":     nome,
        "cognome":  cognome,
        "ruolo":    ruolo,
        "azienda":  azienda,
        "location": location,
        "linkedin": linkedin,
        "headline": ruolo,
        "sommario": summary,
        "source":   "linkedin",
    }


def normalizza_profilo_indeed(p: dict) -> dict:
    """
    Converte un job listing Indeed in profilo sintetico.
    L'azienda che cerca quella figura diventa un lead da contattare.
    source='indeed'.
    """
    title   = _str(p.get("positionName") or p.get("title") or p.get("jobTitle") or "")
    company = _str(p.get("company") or p.get("companyName") or "")
    if not company:
        company = "Azienda non specificata"
    location = _str(p.get("location") or p.get("jobLocation") or p.get("city") or "")
    desc     = _str(p.get("description") or p.get("jobDescription") or p.get("snippet") or "")[:200]
    url      = _str(p.get("url") or p.get("jobUrl") or p.get("applyUrl") or "")

    return {
        "nome":     company,
        "cognome":  "",
        "ruolo":    title,
        "azienda":  company,
        "location": location,
        "linkedin": url,
        "headline": f"Cerca: {title}" if title else "",
        "sommario": desc,
        "source":   "indeed",
    }


def normalizza_profilo_infojobs(p: dict) -> dict:
    """
    Converte un job listing InfoJobs in profilo sintetico.
    L'azienda che cerca quella figura diventa un lead da contattare.
    source='infojobs'.
    Output crawlerbros~infojobs-scraper: title, companyName, city, url, descriptionText, contractType, salary, teleworking.
    """
    title   = _str(p.get("title") or p.get("jobTitle") or p.get("positionName") or "")
    company = _str(p.get("companyName") or p.get("company") or p.get("employer") or "")
    if not company:
        company = "Azienda non specificata"
    location = _str(p.get("city") or p.get("location") or p.get("province") or "")
    desc     = _str(p.get("descriptionText") or p.get("description") or p.get("jobDescription") or "")[:200]
    url      = _str(p.get("url") or p.get("jobUrl") or p.get("link") or "")

    return {
        "nome":     company,
        "cognome":  "",
        "ruolo":    title,
        "azienda":  company,
        "location": location,
        "linkedin": url,
        "headline": f"Cerca: {title}" if title else "",
        "sommario": desc,
        "source":   "infojobs",
    }
