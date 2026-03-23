"""
Gestione del database SQLite per SABIA Recruiting Tool.
Crea le tabelle e fornisce la connessione al database.
"""

import sqlite3
import os

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "sabia.db")


def get_db():
    """Restituisce una connessione al database con row_factory per accesso a colonne per nome."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inizializza il database creando le tabelle se non esistono."""
    conn = get_db()
    cur = conn.cursor()

    # Tabella candidati
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidati (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            ruolo_attuale TEXT,
            azienda TEXT,
            anni_esperienza INTEGER,
            note TEXT,
            profilo_linkedin TEXT,
            tipo_profilo TEXT DEFAULT 'A',
            stato TEXT DEFAULT 'Da contattare',
            punteggio INTEGER,
            analisi TEXT,
            spunti TEXT,
            messaggio_outreach TEXT,
            data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_aggiornamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabella cronologia valutazioni (ogni analisi viene sempre salvata)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS valutazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_contatto TEXT,
            ruolo_attuale TEXT,
            azienda TEXT,
            anni_esperienza INTEGER,
            tipo_profilo TEXT DEFAULT 'A',
            anteprima_testo TEXT,
            punteggio INTEGER,
            analisi TEXT,
            spunti TEXT,
            messaggio_outreach TEXT,
            candidato_id INTEGER,
            data_valutazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrazioni per DB esistenti
    for colonna in [
        "ALTER TABLE valutazioni ADD COLUMN nome_contatto TEXT",
        "ALTER TABLE valutazioni ADD COLUMN ruolo_attuale TEXT",
        "ALTER TABLE valutazioni ADD COLUMN azienda TEXT",
        "ALTER TABLE valutazioni ADD COLUMN anni_esperienza INTEGER",
    ]:
        try:
            cur.execute(colonna)
        except Exception:
            pass  # colonna già esistente

    # Tabella contenuti LinkedIn generati
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contenuti_linkedin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema TEXT NOT NULL,
            tono TEXT NOT NULL,
            profilo_destinazione TEXT NOT NULL,
            variante_1 TEXT,
            variante_2 TEXT,
            variante_3 TEXT,
            data_creazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabella impostazioni profili A e B
    cur.execute("""
        CREATE TABLE IF NOT EXISTS impostazioni_profilo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profilo TEXT NOT NULL UNIQUE,
            eta_min INTEGER DEFAULT 0,
            eta_max INTEGER DEFAULT 99,
            anni_esperienza_min INTEGER DEFAULT 0,
            settori TEXT DEFAULT '',
            istituti TEXT DEFAULT '',
            ruoli_target TEXT DEFAULT '',
            keyword_positive TEXT DEFAULT '',
            keyword_negative TEXT DEFAULT '',
            peso_eta INTEGER DEFAULT 5,
            peso_esperienza INTEGER DEFAULT 5,
            peso_settore INTEGER DEFAULT 5,
            peso_ruolo INTEGER DEFAULT 5,
            peso_keyword INTEGER DEFAULT 5,
            data_aggiornamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabella cronologia ricerche automatiche Apify
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ricerche_automatiche (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_profilo TEXT DEFAULT 'A',
            parametri TEXT,
            profili_trovati INTEGER DEFAULT 0,
            profili_importati INTEGER DEFAULT 0,
            punteggio_medio REAL,
            stato TEXT DEFAULT 'completata',
            data_ricerca TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrazioni per DB esistenti (colonne aggiunte in versioni successive)
    for colonna in [
        "ALTER TABLE valutazioni ADD COLUMN fonte TEXT DEFAULT 'manuale'",
        "ALTER TABLE candidati ADD COLUMN ricerca_id INTEGER",
    ]:
        try:
            cur.execute(colonna)
        except Exception:
            pass  # colonna già esistente

    conn.commit()
    conn.close()
