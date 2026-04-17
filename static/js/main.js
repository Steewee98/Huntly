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

/* ------------------------------------------------------------------ */
/* Utility HTML                                                         */
/* ------------------------------------------------------------------ */
function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/* ------------------------------------------------------------------ */
/* Modal Report AI — condiviso tra ricerca.html e ricerca_dettaglio    */
/* ------------------------------------------------------------------ */
function chiudiModalReport() {
    var el = document.getElementById('modal-report');
    if (el) el.classList.add('hidden');
}

/**
 * Popola e apre il modal-report con i dati di analisi (base o arricchiti).
 * @param {Object} dati - risultato SSE o da DB (stesso schema)
 */
function _mostraReportNelModal(dati) {
    var spinnerEl = document.getElementById('modal-report-spinner');
    var streamEl  = document.getElementById('modal-report-streaming');
    var bodyEl    = document.getElementById('modal-report-body');

    if (spinnerEl) spinnerEl.style.display = 'none';
    if (streamEl)  streamEl.classList.add('hidden');
    if (bodyEl)    bodyEl.classList.remove('hidden');

    var arricchito = !!dati.arricchito;
    var punteggio  = dati.punteggio || 0;
    var scoreClass = punteggio >= 8 ? 'score-alto' : (punteggio >= 5 ? 'score-medio' : 'score-basso');

    var html = '';

    if (arricchito) {
        html += '<div style="margin-bottom:1rem;">' +
            '<span style="font-size:0.75rem;padding:3px 10px;border-radius:20px;' +
            'background:#dbeafe;color:#1e40af;font-weight:600;">&#11088; Profilo Arricchito</span></div>';
    }

    html += '<div class="report-sezione" style="text-align:center;">' +
        '<div class="report-score ' + scoreClass + '">' + punteggio + '/10</div></div>';

    if (arricchito) {
        var _card = function(label, val) {
            var v = (val != null) ? val : '—';
            var c = '#374151';
            if (typeof v === 'number') { c = v >= 8 ? '#16a34a' : (v >= 5 ? '#d97706' : '#dc2626'); }
            return '<div style="background:#f8fafc;border:1px solid var(--grigio-bordo);' +
                'border-radius:var(--radius);padding:0.75rem;text-align:center;">' +
                '<div style="font-size:1.3rem;font-weight:700;color:' + c + ';">' + v + '</div>' +
                '<div style="font-size:0.78rem;color:var(--grigio-testo);margin-top:0.2rem;">' + label + '</div></div>';
        };
        html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.75rem;margin-bottom:1.25rem;">' +
            _card('Compatibilità', dati.punteggio_compatibilita) +
            _card('Mobilità', dati.indice_mobilita) +
            _card('Qualità Profilo', dati.punteggio_qualita_profilo) +
            '</div>';

        if (dati.pattern_carriera) {
            var _pIcons  = {in_crescita:'&#8593; ', stabile:'&mdash; ', in_stallo:'&#9646; ', dinamico:'&#8635; ', instabile:'&#9888; '};
            var _pColors = {in_crescita:'#16a34a', stabile:'#2E7CF6', in_stallo:'#d97706', dinamico:'#2E7CF6', instabile:'#dc2626'};
            var pk = dati.pattern_carriera.toLowerCase().replace(/ /g, '_');
            html += '<div class="report-sezione"><h4>Pattern Carriera</h4>' +
                '<p style="color:' + (_pColors[pk] || '#374151') + ';font-weight:600;">' +
                (_pIcons[pk] || '') + escHtml(dati.pattern_carriera) + '</p></div>';
        }

        if (dati.momento_contatto) {
            var _mColors = {ora:'#16a34a', '6_mesi':'#d97706', '1_anno':'#ca8a04', non_adatto:'#dc2626'};
            var _mLabel  = {ora:'Ora', '6_mesi':'Tra 6 mesi', '1_anno':'Tra 1 anno', non_adatto:'Non adatto'};
            var mk = dati.momento_contatto.toLowerCase();
            var mColor = _mColors[mk] || '#374151';
            html += '<div class="report-sezione"><h4>Momento Contatto</h4>' +
                '<span style="display:inline-block;padding:3px 12px;border-radius:20px;font-size:0.85rem;font-weight:600;' +
                'background:' + mColor + '1a;color:' + mColor + ';border:1px solid ' + mColor + ';">' +
                escHtml(_mLabel[mk] || dati.momento_contatto) + '</span></div>';
        }

        if (dati.sintesi) {
            html += '<div class="report-sezione"><h4>Sintesi</h4>' +
                '<p style="background:#f8fafc;border-radius:var(--radius);padding:0.75rem;">' +
                escHtml(dati.sintesi) + '</p></div>';
        }

        var spPos = dati.segnali_positivi;
        if (spPos && spPos.length) {
            html += '<div class="report-sezione"><h4 style="color:#16a34a;">&#10003; Segnali Positivi</h4><ul>' +
                spPos.map(function(s) { return '<li style="color:#15803d;">' + escHtml(s) + '</li>'; }).join('') +
                '</ul></div>';
        }

        var spNeg = dati.segnali_negativi;
        if (spNeg && spNeg.length) {
            html += '<div class="report-sezione"><h4 style="color:#dc2626;">&#10007; Segnali Negativi</h4><ul>' +
                spNeg.map(function(s) { return '<li style="color:#b91c1c;">' + escHtml(s) + '</li>'; }).join('') +
                '</ul></div>';
        }

        var rischi = dati.rischi;
        if (rischi && rischi.length) {
            html += '<div class="report-sezione"><h4 style="color:#d97706;">&#9888; Rischi</h4><ul>' +
                rischi.map(function(s) { return '<li style="color:#b45309;">' + escHtml(s) + '</li>'; }).join('') +
                '</ul></div>';
        }

        if (dati.analisi_attivita) {
            html += '<div class="report-sezione"><h4>Attività LinkedIn</h4>' +
                '<p style="background:#eff6ff;border-left:3px solid #2E7CF6;padding:0.75rem;' +
                'border-radius:0 var(--radius) var(--radius) 0;">' +
                escHtml(dati.analisi_attivita) + '</p></div>';
        }

        if (dati.motivazione_probabile) {
            html += '<div class="report-sezione"><h4>Motivazione Probabile</h4>' +
                '<p>' + escHtml(dati.motivazione_probabile) + '</p></div>';
        }
    }

    html += '<div class="report-sezione"><h4>Analisi del Percorso</h4>' +
        '<p>' + escHtml(dati.analisi_percorso || '—') + '</p></div>';

    var spunti = dati.spunti_contatto || dati.spunti || [];
    if (typeof spunti === 'string') { try { spunti = JSON.parse(spunti); } catch(e) { spunti = []; } }
    if (spunti.length) {
        html += '<div class="report-sezione"><h4>Spunti per il Contatto</h4><ul>' +
            spunti.map(function(s) { return '<li class="spunto-item">' + escHtml(s) + '</li>'; }).join('') +
            '</ul></div>';
    }

    if (arricchito && dati.messaggio_personalizzato) {
        html += '<div class="report-sezione"><h4>&#9993; Messaggio Personalizzato</h4>' +
            '<div class="outreach-box">' + escHtml(dati.messaggio_personalizzato) + '</div></div>';
    } else if (dati.messaggio_outreach) {
        html += '<div class="report-sezione"><h4>Messaggio di Outreach</h4>' +
            '<div class="outreach-box">' + escHtml(dati.messaggio_outreach) + '</div></div>';
    }

    if (bodyEl) bodyEl.innerHTML = html;
    mostra('modal-report');
}
