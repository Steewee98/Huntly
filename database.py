"""
Gestione del database PostgreSQL per Huntly.
Usa psycopg2 con DATABASE_URL fornita da Railway.

Il wrapper _PgConnection / _PgCursor mantiene la stessa interfaccia
di sqlite3 usata in tutta l'app (execute / commit / close / lastrowid / fetchone / fetchall)
senza dover modificare nessun file route.
"""

import os
import re
import time
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, date

_log = logging.getLogger(__name__)

# Soglie di log per query lente (secondi)
_SLOW_QUERY_WARN  = 0.10   # WARNING se supera 100ms
_SLOW_QUERY_DEBUG = 0.02   # DEBUG   se supera 20ms


# ─────────────────────────────────────────────
# Helpers interni
# ─────────────────────────────────────────────

def _get_raw_connection():
    """Apre una connessione psycopg2 usando DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL non configurata. "
            "Aggiungi un database PostgreSQL in Railway (Add Service → Database → PostgreSQL)."
        )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def _serialize_row(row):
    """
    Converte un RealDictRow PostgreSQL in un dict con datetime → stringa ISO.
    I template usano slicing tipo data[:10] e data[11:16], che funziona
    solo con stringhe — psycopg2 restituisce oggetti datetime.
    """
    if row is None:
        return None
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            result[k] = v.strftime("%Y-%m-%d")
        else:
            result[k] = v
    return result


# ─────────────────────────────────────────────
# Wrapper cursore
# ─────────────────────────────────────────────

class _PgCursor:
    """
    Cursore compatibile con sqlite3: espone lastrowid, fetchone, fetchall.
    lastrowid viene popolato durante execute() sugli INSERT con RETURNING id.
    """

    def __init__(self, cursor, lastrowid=None):
        self._cur = cursor
        self.lastrowid = lastrowid

    def fetchall(self):
        try:
            rows = self._cur.fetchall()
            return [_serialize_row(r) for r in (rows or [])]
        except psycopg2.ProgrammingError:
            return []

    def fetchone(self):
        try:
            return _serialize_row(self._cur.fetchone())
        except psycopg2.ProgrammingError:
            return None


# ─────────────────────────────────────────────
# Wrapper connessione
# ─────────────────────────────────────────────

class _PgConnection:
    """
    Connessione compatibile con sqlite3.
    Converte automaticamente i placeholder ? in %s e aggiunge
    RETURNING id agli INSERT per emulare cur.lastrowid.
    """

    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql, params=None):
        # Converti placeholder SQLite → psycopg2
        pg_sql = sql.replace("?", "%s")

        # Aggiunge RETURNING id agli INSERT per ottenere lastrowid.
        # Usa un savepoint: se la tabella non ha colonna 'id' (es. job_ricerche),
        # fa rollback al savepoint ed esegue senza RETURNING.
        is_insert = bool(re.match(r"\s*INSERT\b", pg_sql, re.IGNORECASE))
        needs_returning = is_insert and "RETURNING" not in pg_sql.upper()
        pg_sql_ret = (pg_sql.rstrip().rstrip(";") + " RETURNING id") if needs_returning else pg_sql

        t0 = time.perf_counter()
        lastrowid = None

        if needs_returning:
            self._cur.execute("SAVEPOINT _ret")
            try:
                if params is not None:
                    self._cur.execute(pg_sql_ret, params)
                else:
                    self._cur.execute(pg_sql_ret)
                # fetchone() deve avvenire PRIMA di RELEASE SAVEPOINT:
                # dopo il RELEASE il cursore punta al risultato del comando DDL
                # (nessuna riga), causando ProgrammingError: no results to fetch
                row = self._cur.fetchone()
                lastrowid = row["id"] if row else None
                self._cur.execute("RELEASE SAVEPOINT _ret")
            except psycopg2.errors.UndefinedColumn:
                # Tabella senza colonna 'id' — esegui senza RETURNING
                self._cur.execute("ROLLBACK TO SAVEPOINT _ret")
                self._cur.execute("RELEASE SAVEPOINT _ret")
                if params is not None:
                    self._cur.execute(pg_sql, params)
                else:
                    self._cur.execute(pg_sql)
        else:
            if params is not None:
                self._cur.execute(pg_sql, params)
            else:
                self._cur.execute(pg_sql)

        elapsed = time.perf_counter() - t0

        # Log query lente
        if elapsed >= _SLOW_QUERY_WARN:
            _log.warning("Query lenta (%.0fms): %s", elapsed * 1000, pg_sql.strip()[:120])
        elif elapsed >= _SLOW_QUERY_DEBUG:
            _log.debug("Query (%.0fms): %s", elapsed * 1000, pg_sql.strip()[:120])

        return _PgCursor(self._cur, lastrowid)

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────

def get_db():
    """Restituisce una connessione al database pronta all'uso."""
    return _PgConnection(_get_raw_connection())


def init_db():
    """
    Inizializza il database creando le tabelle se non esistono.
    Ogni DDL viene eseguito in un savepoint separato: se fallisce
    (es. tipo omonimo già esistente in PostgreSQL) viene fatto rollback
    solo di quel singolo statement e si continua con i successivi.
    """
    import logging
    log = logging.getLogger(__name__)

    # Usa la connessione raw psycopg2 per gestire i savepoint direttamente
    raw_conn = _get_raw_connection()
    cur = raw_conn.cursor()

    statements = [
        # ── Tabella candidati ──────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS candidati (
            id                  SERIAL PRIMARY KEY,
            nome                TEXT NOT NULL,
            cognome             TEXT NOT NULL,
            ruolo_attuale       TEXT,
            azienda             TEXT,
            anni_esperienza     INTEGER,
            note                TEXT,
            profilo_linkedin    TEXT,
            tipo_profilo        TEXT DEFAULT 'A',
            stato               TEXT DEFAULT 'Da contattare',
            punteggio           INTEGER,
            analisi             TEXT,
            spunti              TEXT,
            messaggio_outreach  TEXT,
            ricerca_id          INTEGER,
            data_inserimento    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_aggiornamento  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        # ── Tabella valutazioni ────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS valutazioni (
            id                  SERIAL PRIMARY KEY,
            nome_contatto       TEXT,
            ruolo_attuale       TEXT,
            azienda             TEXT,
            anni_esperienza     INTEGER,
            tipo_profilo        TEXT DEFAULT 'A',
            anteprima_testo     TEXT,
            punteggio           INTEGER,
            analisi             TEXT,
            spunti              TEXT,
            messaggio_outreach  TEXT,
            candidato_id        INTEGER,
            fonte               TEXT DEFAULT 'manuale',
            data_valutazione    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        # ── Tabella contenuti LinkedIn ─────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS contenuti_linkedin (
            id                      SERIAL PRIMARY KEY,
            tema                    TEXT NOT NULL,
            tono                    TEXT NOT NULL,
            profilo_destinazione    TEXT NOT NULL,
            variante_1              TEXT,
            variante_2              TEXT,
            variante_3              TEXT,
            data_creazione          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        # ── Tabella profili voce autore (contenuti LinkedIn) ───────────────
        """CREATE TABLE IF NOT EXISTS profili_voce (
    id                SERIAL PRIMARY KEY,
    nome              VARCHAR(100) NOT NULL,
    linkedin_url      TEXT,
    linkedin_summary  TEXT,
    settore           TEXT,
    tono_prevalente   TEXT,
    bio_breve         TEXT,
    creato_il         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        # ── Tabella analisi profilo personale LinkedIn ────────────────────
        """CREATE TABLE IF NOT EXISTS analisi_profilo (
    id                    SERIAL PRIMARY KEY,
    linkedin_url          TEXT,
    punteggio             INTEGER,
    headline_attuale      TEXT,
    headline_suggerita    TEXT,
    about_attuale         TEXT,
    about_suggerito       TEXT,
    punti_forza           TEXT,
    aree_miglioramento    TEXT,
    keyword_mancanti      TEXT,
    dati_raw              TEXT,
    creato_il             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",

        # Nuovi campi per storico contenuti con profilo voce
        "ALTER TABLE contenuti_linkedin ADD COLUMN IF NOT EXISTS obiettivo TEXT",
        "ALTER TABLE contenuti_linkedin ADD COLUMN IF NOT EXISTS contesto TEXT",
        "ALTER TABLE contenuti_linkedin ADD COLUMN IF NOT EXISTS profilo_voce_id INTEGER",

        # ── Tabella impostazioni profili A e B ─────────────────────────────
        """CREATE TABLE IF NOT EXISTS impostazioni_profilo (
            id                  SERIAL PRIMARY KEY,
            profilo             TEXT NOT NULL UNIQUE,
            eta_min             INTEGER DEFAULT 0,
            eta_max             INTEGER DEFAULT 99,
            anni_esperienza_min INTEGER DEFAULT 0,
            settori             TEXT DEFAULT '',
            istituti            TEXT DEFAULT '',
            ruoli_target        TEXT DEFAULT '',
            keyword_positive    TEXT DEFAULT '',
            keyword_negative    TEXT DEFAULT '',
            peso_eta            INTEGER DEFAULT 5,
            peso_esperienza     INTEGER DEFAULT 5,
            peso_settore        INTEGER DEFAULT 5,
            peso_ruolo          INTEGER DEFAULT 5,
            peso_keyword        INTEGER DEFAULT 5,
            data_aggiornamento  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        # ── Tabella cronologia ricerche ────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS ricerche_automatiche (
            id                  SERIAL PRIMARY KEY,
            tipo_profilo        TEXT DEFAULT 'A',
            parametri           TEXT,
            profili_trovati     INTEGER DEFAULT 0,
            profili_importati   INTEGER DEFAULT 0,
            punteggio_medio     REAL,
            stato               TEXT DEFAULT 'completata',
            fonte               TEXT DEFAULT 'apify',
            data_ricerca        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        # ── Tabella profili trovati nelle ricerche ──────────────────────────
        # Salva il testo completo di ogni profilo trovato, collegato alla ricerca.
        # Rimane permanente anche dopo eventuali cancellazioni di candidati.
        """CREATE TABLE IF NOT EXISTS profili_ricerca (
            id            SERIAL PRIMARY KEY,
            ricerca_id    INTEGER NOT NULL,
            nome          TEXT,
            cognome       TEXT,
            ruolo         TEXT,
            azienda       TEXT,
            location      TEXT,
            linkedin_url  TEXT,
            testo_profilo TEXT,
            candidato_id  INTEGER,
            data_trovato  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        # ── Tabella job ricerche asincrone ─────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS job_ricerche (
            job_id      TEXT PRIMARY KEY,
            tipo_profilo TEXT DEFAULT 'A',
            status      TEXT DEFAULT 'avviato',
            step        TEXT DEFAULT '',
            risultati   TEXT,
            errore      TEXT,
            data_inizio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_fine   TIMESTAMP
        )""",

        # ── Migrazioni colonne ─────────────────────────────────────────────
        "ALTER TABLE valutazioni          ADD COLUMN IF NOT EXISTS nome_contatto TEXT",
        "ALTER TABLE valutazioni          ADD COLUMN IF NOT EXISTS ruolo_attuale TEXT",
        "ALTER TABLE valutazioni          ADD COLUMN IF NOT EXISTS azienda TEXT",
        "ALTER TABLE valutazioni          ADD COLUMN IF NOT EXISTS anni_esperienza INTEGER",
        "ALTER TABLE valutazioni          ADD COLUMN IF NOT EXISTS fonte TEXT DEFAULT 'manuale'",
        "ALTER TABLE candidati            ADD COLUMN IF NOT EXISTS ricerca_id INTEGER",
        "ALTER TABLE ricerche_automatiche ADD COLUMN IF NOT EXISTS fonte TEXT DEFAULT 'apify'",
        # Deduplicazione: indice parziale su LinkedIn (esclude NULL e stringa vuota)
        "CREATE INDEX IF NOT EXISTS idx_candidati_linkedin ON candidati(profilo_linkedin) WHERE profilo_linkedin IS NOT NULL AND profilo_linkedin <> ''",
        # Indice UNIQUE su LinkedIn — silenziosamente ignorato se esistono già duplicati
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidati_linkedin_unique ON candidati(profilo_linkedin) WHERE profilo_linkedin IS NOT NULL AND profilo_linkedin <> ''",
        # Percentuale avanzamento ricerca asincrona
        "ALTER TABLE job_ricerche ADD COLUMN IF NOT EXISTS percentuale INTEGER DEFAULT 0",
        # Gestore candidato
        "ALTER TABLE candidati ADD COLUMN IF NOT EXISTS gestore TEXT DEFAULT 'Non assegnato'",

        # Multi-source: sorgente di provenienza del profilo
        "ALTER TABLE profili_ricerca ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'linkedin'",
        "ALTER TABLE candidati       ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'linkedin'",

        # Arricchimento Proxycurl
        "ALTER TABLE candidati   ADD COLUMN IF NOT EXISTS dati_proxycurl TEXT",
        "ALTER TABLE candidati   ADD COLUMN IF NOT EXISTS dati_arricchiti TEXT",
        "ALTER TABLE valutazioni ADD COLUMN IF NOT EXISTS dati_arricchiti TEXT",

        # ── Tabella appuntamenti ────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS appuntamenti (
    id              SERIAL PRIMARY KEY,
    candidato_id    INTEGER,
    gestore         TEXT NOT NULL,
    tipo            TEXT NOT NULL,
    data_ora        TIMESTAMP NOT NULL,
    note            TEXT,
    stato           TEXT DEFAULT 'Da fare',
    data_creazione  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",

        # ── Tabella offset ricerche (variazione query ad ogni ricerca) ────────
        """CREATE TABLE IF NOT EXISTS search_offset (
    tipo_profilo         TEXT PRIMARY KEY,
    offset_corrente      INTEGER DEFAULT 0,
    indice_ruolo         INTEGER DEFAULT 0,
    indice_citta         INTEGER DEFAULT 0,
    ultimo_aggiornamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",

        # ── Tabella profili scartati (blacklist) ───────────────────────────
        """CREATE TABLE IF NOT EXISTS profili_scartati (
    id           SERIAL PRIMARY KEY,
    linkedin_url TEXT,
    nome         TEXT,
    cognome      TEXT,
    ruolo        TEXT,
    azienda      TEXT,
    motivo       TEXT DEFAULT 'non_importato',
    data_scarto  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        "CREATE INDEX IF NOT EXISTS idx_profili_scartati_linkedin ON profili_scartati(linkedin_url) WHERE linkedin_url IS NOT NULL AND linkedin_url <> ''",

        # ── Tabella organizzazioni (multi-tenant) ─────────────────────────
        """CREATE TABLE IF NOT EXISTS organizzazioni (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(100) NOT NULL,
    slug      VARCHAR(50) UNIQUE NOT NULL,
    piano     VARCHAR(20) DEFAULT 'free',
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        # Organizzazione default per dati legacy
        """INSERT INTO organizzazioni (nome, slug, piano)
           VALUES ('Default', 'default', 'pro')
           ON CONFLICT (slug) DO NOTHING""",

        # ── Tabella utenti ────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS utenti (
    id                  SERIAL PRIMARY KEY,
    organizzazione_id   INTEGER REFERENCES organizzazioni(id),
    email               VARCHAR(120) UNIQUE NOT NULL,
    password_hash       TEXT NOT NULL,
    nome                VARCHAR(100),
    ruolo               VARCHAR(20) DEFAULT 'admin',
    attivo              BOOLEAN DEFAULT TRUE,
    creato_il           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",

        # ── organizzazione_id su tutte le tabelle principali ──────────────
        "ALTER TABLE candidati           ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE profili_voce        ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE ricerche_automatiche ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE analisi_profilo     ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE valutazioni         ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE appuntamenti        ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE contenuti_linkedin  ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "ALTER TABLE impostazioni_profilo ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",

        # Migra dati legacy all'organizzazione default (id=1)
        "UPDATE candidati            SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE profili_voce         SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE ricerche_automatiche SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE analisi_profilo      SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE valutazioni          SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE appuntamenti         SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE contenuti_linkedin   SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "UPDATE impostazioni_profilo SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",

        # ── Tabella profili target configurabili ───────────────────────────
        """CREATE TABLE IF NOT EXISTS profili_target (
    id                    SERIAL PRIMARY KEY,
    nome                  TEXT NOT NULL,
    descrizione           TEXT DEFAULT '',
    ruoli_target          TEXT DEFAULT '',
    settori               TEXT DEFAULT '',
    eta_min               INTEGER DEFAULT 0,
    eta_max               INTEGER DEFAULT 99,
    anni_esperienza_min   INTEGER DEFAULT 0,
    keyword_positive      TEXT DEFAULT '',
    keyword_negative      TEXT DEFAULT '',
    colore                VARCHAR(20) DEFAULT '#6366f1',
    attivo                BOOLEAN DEFAULT TRUE,
    creato_il             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        "ALTER TABLE profili_target ADD COLUMN IF NOT EXISTS organizzazione_id INTEGER",
        "UPDATE profili_target SET organizzazione_id = 1 WHERE organizzazione_id IS NULL",
        "ALTER TABLE profili_target ADD COLUMN IF NOT EXISTS scopo VARCHAR(50) DEFAULT 'recruiting'",
        "ALTER TABLE profili_target ADD COLUMN IF NOT EXISTS scopo_dettaglio TEXT",
        # Seed: 2 profili generici se la tabella è vuota
        """INSERT INTO profili_target (nome, descrizione, ruoli_target, settori, eta_min, eta_max, anni_esperienza_min, keyword_positive, colore)
SELECT 'Profilo Senior', 'Figure manageriali con almeno 10 anni di esperienza', '', '', 40, 65, 10, '', '#6366f1'
WHERE NOT EXISTS (SELECT 1 FROM profili_target)""",
        """INSERT INTO profili_target (nome, descrizione, ruoli_target, settori, eta_min, eta_max, anni_esperienza_min, keyword_positive, colore)
SELECT 'Profilo Junior', 'Profili emergenti under 35 con forte potenziale', '', '', 22, 35, 0, '', '#16a34a'
WHERE NOT EXISTS (SELECT 1 FROM profili_target WHERE nome = 'Profilo Junior')""",

        # ── Utilizzo mensile per feature gating ───────────────────────────
        """CREATE TABLE IF NOT EXISTS utilizzo_mensile (
    id                SERIAL PRIMARY KEY,
    organizzazione_id INTEGER REFERENCES organizzazioni(id),
    mese              VARCHAR(7) NOT NULL,
    ricerche          INTEGER DEFAULT 0,
    analisi_ai        INTEGER DEFAULT 0,
    creato_il         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organizzazione_id, mese)
)""",

        # ── Inviti team ────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS inviti_team (
    id                SERIAL PRIMARY KEY,
    organizzazione_id INTEGER REFERENCES organizzazioni(id),
    email             VARCHAR(120) NOT NULL,
    token             VARCHAR(100) UNIQUE NOT NULL,
    accettato         BOOLEAN DEFAULT FALSE,
    creato_il         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",

        # ── Calendly + email candidato ────────────────────────────────────
        "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS calendly_url TEXT",
        "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS email_mittente TEXT",
        "ALTER TABLE candidati ADD COLUMN IF NOT EXISTS email TEXT",

        # ── Admin flag ────────────────────────────────────────────────────
        "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",

        # ── Indici per performance query ───────────────────────────────────
        "CREATE INDEX IF NOT EXISTS idx_candidati_tipo_profilo  ON candidati(tipo_profilo)",
        "CREATE INDEX IF NOT EXISTS idx_candidati_stato          ON candidati(stato)",
        "CREATE INDEX IF NOT EXISTS idx_candidati_data_ins       ON candidati(data_inserimento DESC)",
        "CREATE INDEX IF NOT EXISTS idx_candidati_punteggio      ON candidati(punteggio)",
        "CREATE INDEX IF NOT EXISTS idx_valutazioni_data         ON valutazioni(data_valutazione DESC)",
        "CREATE INDEX IF NOT EXISTS idx_valutazioni_tipo         ON valutazioni(tipo_profilo)",
        "CREATE INDEX IF NOT EXISTS idx_valutazioni_punteggio    ON valutazioni(punteggio)",
        "CREATE INDEX IF NOT EXISTS idx_ricerche_data            ON ricerche_automatiche(data_ricerca DESC)",
        "CREATE INDEX IF NOT EXISTS idx_ricerche_tipo            ON ricerche_automatiche(tipo_profilo)",
        "CREATE INDEX IF NOT EXISTS idx_profili_ricerca_id       ON profili_ricerca(ricerca_id)",
        "CREATE INDEX IF NOT EXISTS idx_profili_candidato_id     ON profili_ricerca(candidato_id)",
    ]

    for i, sql in enumerate(statements):
        sp = f"huntly_init_{i}"
        cur.execute(f"SAVEPOINT {sp}")
        try:
            cur.execute(sql)
            cur.execute(f"RELEASE SAVEPOINT {sp}")
        except psycopg2.Error as e:
            cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            log.warning("init_db: DDL ignorato [%s]: %s", type(e).__name__, sql.strip()[:80])

    raw_conn.commit()
    cur.close()
    raw_conn.close()
