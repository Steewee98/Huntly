/**
 * SABIA Recruiting Tool — Script JavaScript condiviso
 * Funzioni di utilità usate da tutti i moduli
 */

/**
 * Mostra un elemento nascosto rimuovendo la classe 'hidden'
 * @param {string} id - ID dell'elemento
 */
function mostra(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
}

/**
 * Nasconde un elemento aggiungendo la classe 'hidden'
 * @param {string} id - ID dell'elemento
 */
function nascondi(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
}

/**
 * Apre/chiude un gruppo espandibile nella sidebar
 */
function toggleGroup(btn) {
    const items = btn.nextElementSibling;
    btn.classList.toggle('open');
    items.classList.toggle('open');
}

/**
 * Chiude i modal premendo il tasto ESC
 */
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        // Chiudi tutti i modal aperti
        document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(modal => {
            modal.classList.add('hidden');
        });
    }
});

/**
 * Legge la response come testo e poi fa JSON.parse con gestione errori esplicita.
 * Evita il SyntaxError di Safari quando il server restituisce HTML invece di JSON.
 * @param {Response} response - oggetto Response da fetch()
 * @returns {Promise<any>} - dati JSON parsati
 */
async function jsonSicuro(response) {
    const testo = await response.text();
    try {
        return JSON.parse(testo);
    } catch (e) {
        console.error('[jsonSicuro] Risposta non JSON (status ' + response.status + '):', testo.substring(0, 300));
        throw new Error('Risposta del server non valida: ' + testo.substring(0, 100));
    }
}
