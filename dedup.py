"""
Deduplicazione centralizzata profili — SABIA Recruiting Tool.

is_duplicate(db, profilo) è l'unico punto di verifica usato in tutto
il codebase: ricerca automatica, ricerca manuale, inserimento form.
"""

from urllib.parse import urlparse


# ─────────────────────────────────────────────
# URL LinkedIn normalizzato
# ─────────────────────────────────────────────

def _normalize_linkedin(url: str) -> str:
    """
    Normalizza un URL LinkedIn per confronto uniforme:
    - lowercase
    - rimuove 'www.'
    - rimuove trailing slash
    - rimuove query string e fragment (UTM, ecc.)
    Esempi:
      https://www.linkedin.com/in/mario-rossi/  →  linkedin.com/in/mario-rossi
      https://linkedin.com/in/mario-rossi?utm=x →  linkedin.com/in/mario-rossi
    """
    if not url:
        return ""
    try:
        url = url.strip().lower()
        p = urlparse(url)
        host = p.netloc.replace("www.", "") or "linkedin.com"
        path = p.path.rstrip("/")
        return host + path
    except Exception:
        return url.strip().rstrip("/").lower()


# ─────────────────────────────────────────────
# Funzione pubblica
# ─────────────────────────────────────────────

def is_duplicate(db, profilo: dict) -> tuple:
    """
    Verifica se il profilo esiste già nella tabella candidati.

    Ordine di priorità:
      1. LinkedIn URL (normalizzato) — controllo più affidabile
      2. nome + cognome + azienda (case-insensitive, strip)
      3. nome + cognome + ruolo (fallback se azienda mancante)

    Returns:
        (is_dup: bool, motivo: str, candidato_id: int | None)
    """
    # ── 1. LinkedIn URL ───────────────────────────────────────────────────────
    linkedin = (
        profilo.get("linkedin") or profilo.get("linkedin_url") or
        profilo.get("profilo_linkedin") or ""
    ).strip()

    if linkedin:
        linkedin_norm = _normalize_linkedin(linkedin)
        rows = db.execute(
            "SELECT id, profilo_linkedin FROM candidati "
            "WHERE profilo_linkedin IS NOT NULL AND profilo_linkedin <> ''"
        ).fetchall()
        for row in rows:
            if _normalize_linkedin(row["profilo_linkedin"]) == linkedin_norm:
                return True, f"URL LinkedIn già presente", row["id"]

    # ── 2. nome + cognome + azienda ───────────────────────────────────────────
    nome    = (profilo.get("nome") or profilo.get("first_name") or "").strip().lower()
    cognome = (profilo.get("cognome") or profilo.get("last_name") or "").strip().lower()
    azienda = (profilo.get("azienda") or profilo.get("company") or "").strip().lower()
    ruolo   = (
        profilo.get("ruolo") or profilo.get("ruolo_attuale") or
        profilo.get("headline") or ""
    ).strip().lower()

    if nome and cognome and azienda:
        row = db.execute(
            "SELECT id FROM candidati "
            "WHERE LOWER(TRIM(nome))=? AND LOWER(TRIM(cognome))=? "
            "AND LOWER(TRIM(azienda))=?",
            (nome, cognome, azienda),
        ).fetchone()
        if row:
            return True, f"Nome+azienda già presenti ({nome} {cognome} @ {azienda})", row["id"]

    # ── 3. nome + cognome + ruolo (fallback) ──────────────────────────────────
    if nome and cognome and ruolo:
        row = db.execute(
            "SELECT id FROM candidati "
            "WHERE LOWER(TRIM(nome))=? AND LOWER(TRIM(cognome))=? "
            "AND LOWER(TRIM(ruolo_attuale))=?",
            (nome, cognome, ruolo),
        ).fetchone()
        if row:
            return True, f"Nome+ruolo già presenti ({nome} {cognome} — {ruolo})", row["id"]

    return False, "", None
