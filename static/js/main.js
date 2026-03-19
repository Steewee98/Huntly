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
