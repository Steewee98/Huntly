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

    conn.commit()
    conn.close()
