"""
Configurazione globale Huntly.
Limiti per piano SaaS e costanti applicative.
"""

PIANI = {
    'free': {
        'nome': 'Free',
        'prezzo': '€0/mese',
        'candidati_max': 25,
        'ricerche_max': 5,
        'analisi_max': 10,
        'profili_target_max': 1,
        'utenti_max': 1,
        'export_csv': False,
        'colore': '#6B7280',
    },
    'pro': {
        'nome': 'Pro',
        'prezzo': '€49/mese',
        'candidati_max': 300,
        'ricerche_max': 50,
        'analisi_max': 100,
        'profili_target_max': 3,
        'utenti_max': 3,
        'export_csv': True,
        'colore': '#6366f1',
    },
    'business': {
        'nome': 'Business',
        'prezzo': '€149/mese',
        'candidati_max': -1,
        'ricerche_max': 200,
        'analisi_max': 500,
        'profili_target_max': -1,
        'utenti_max': 10,
        'export_csv': True,
        'colore': '#059669',
    },
}
