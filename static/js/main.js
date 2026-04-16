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
/**
 * Mostra un toast arancione (avviso non bloccante) per situazioni come
 * "profilo già presente" (HTTP 409).
 * @param {string} titolo     - Titolo breve
 * @param {string} messaggio  - Descrizione dell'avviso
 * @param {string|null} link  - URL opzionale "Vai alla scheda →"
 */
function mostraAvviso(titolo, messaggio, link) {
    // Rimuovi toast precedente se esiste
    const vecchio = document.getElementById('_toast-avviso');
    if (vecchio) vecchio.remove();

    const toast = document.createElement('div');
    toast.id = '_toast-avviso';
    toast.style.cssText = [
        'position:fixed', 'top:1.25rem', 'right:1.25rem', 'z-index:9999',
        'background:#fff7ed', 'border:1.5px solid #f59e0b', 'border-left:4px solid #f59e0b',
        'border-radius:10px', 'padding:1rem 1.25rem', 'max-width:340px',
        'box-shadow:0 4px 20px rgba(0,0,0,0.12)', 'font-family:inherit',
        'animation:_slideIn 0.2s ease',
    ].join(';');

    const linkHtml = link
        ? '<a href="' + link + '" style="display:inline-block;margin-top:0.5rem;color:#d97706;font-weight:600;text-decoration:none;font-size:0.88rem;">Vai alla scheda →</a>'
        : '';

    toast.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.75rem;">' +
            '<div>' +
                '<div style="font-weight:700;color:#92400e;font-size:0.95rem;margin-bottom:0.2rem;">⚠️ ' + titolo + '</div>' +
                '<div style="color:#78350f;font-size:0.87rem;">' + messaggio + '</div>' +
                linkHtml +
            '</div>' +
            '<button onclick="this.closest(\'#_toast-avviso\').remove()" ' +
                'style="background:none;border:none;cursor:pointer;color:#92400e;font-size:1.1rem;padding:0;flex-shrink:0;">✕</button>' +
        '</div>';

    // Aggiunge animazione CSS inline (una sola volta)
    if (!document.getElementById('_toast-style')) {
        const style = document.createElement('style');
        style.id = '_toast-style';
        style.textContent = '@keyframes _slideIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:translateX(0)}}';
        document.head.appendChild(style);
    }

    document.body.appendChild(toast);
    setTimeout(function() { if (toast.parentNode) toast.remove(); }, 6000);
}

async function jsonSicuro(response) {
    const testo = await response.text();
    try {
        return JSON.parse(testo);
    } catch (e) {
        console.error('[jsonSicuro] Risposta non JSON (status ' + response.status + '):', testo.substring(0, 300));
        throw new Error('Risposta del server non valida: ' + testo.substring(0, 100));
    }
}
