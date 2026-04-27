/**
 * Huntly — Script JavaScript condiviso
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

/* ------------------------------------------------------------------ */
/* Scarta profilo — blacklist (condiviso tra ricerca.html e dettaglio) */
/* ------------------------------------------------------------------ */
function scartaProfilo(p, btn) {
    btn.disabled = true;
    fetch('/ricerca/scarta', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            linkedin: p.linkedin || p.linkedin_url || '',
            nome:     p.nome    || '',
            cognome:  p.cognome || '',
            ruolo:    p.ruolo   || '',
            azienda:  p.azienda || '',
            motivo:   'non_importato'
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.successo) {
            var riga = btn.closest('tr');
            if (riga) {
                riga.style.transition = 'opacity 0.3s';
                riga.style.opacity = '0';
                setTimeout(function() { riga.remove(); }, 300);
            }
            mostraToast('Profilo scartato — non verrà più proposto');
        } else {
            btn.disabled = false;
            alert('Errore durante lo scarto del profilo.');
        }
    })
    .catch(function(err) {
        btn.disabled = false;
        console.error('[scarta]', err);
    });
}

function mostraToast(testo) {
    var toast = document.getElementById('_toast-scarta');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = '_toast-scarta';
        toast.style.cssText = [
            'position:fixed', 'bottom:1.5rem', 'right:1.5rem',
            'background:#1A2E4A', 'color:#fff', 'padding:0.75rem 1.25rem',
            'border-radius:6px', 'font-size:0.875rem', 'z-index:9999',
            'box-shadow:0 4px 12px rgba(0,0,0,0.25)', 'opacity:0',
            'transition:opacity 0.3s'
        ].join(';');
        document.body.appendChild(toast);
    }
    toast.textContent = testo;
    toast.style.opacity = '1';
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(function() { toast.style.opacity = '0'; }, 3000);
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
/* Modal Report AI — condiviso tra tutte le pagine                     */
/* ------------------------------------------------------------------ */

// Stato globale per l'analisi approfondita
var _reportGlobale = null;

function chiudiModalReport() {
    var el = document.getElementById('modal-report');
    if (el) el.classList.add('hidden');
}

/**
 * Popola e apre il modal-report con i dati di analisi (base o arricchiti).
 * @param {Object} dati          - risultato SSE o da DB
 * @param {Object} candidatoInfo - { testo, linkedin_url, candidato_id, tipo_profilo }
 * @param {Function} salvaCallback - function(dati) chiamata dopo analisi approfondita
 */
function _mostraReportNelModal(dati, candidatoInfo, salvaCallback) {
    // Salva contesto per eventuale analisi approfondita
    _reportGlobale = candidatoInfo ? { candidatoInfo: candidatoInfo, salvaCallback: salvaCallback || null } : _reportGlobale;
    _outreachVersioni = [];
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
        '<div class="report-score ' + scoreClass + '">' + punteggio + '/10</div>';

    // Badge scopo ricerca
    var _scopoInfo = candidatoInfo ? (candidatoInfo.scopo || null) : null;
    if (_scopoInfo) {
        var _scopeIcons = {recruiting:'\u{1F3AF}',sales:'\u{1F4BC}',partnership:'\u{1F91D}',network:'\u{1F310}'};
        var _scopeNames = {recruiting:'Recruiting',sales:'Sales',partnership:'Partnership',network:'Network'};
        var _scopeColors = {recruiting:'#6366f1',sales:'#d97706',partnership:'#16a34a',network:'#0891b2'};
        var _sc = _scopoInfo.toLowerCase();
        html += '<div style="margin-top:0.5rem;"><span style="font-size:0.75rem;padding:3px 10px;border-radius:20px;' +
            'background:' + (_scopeColors[_sc] || '#6366f1') + '1a;color:' + (_scopeColors[_sc] || '#6366f1') + ';' +
            'font-weight:600;border:1px solid ' + (_scopeColors[_sc] || '#6366f1') + ';">' +
            (_scopeIcons[_sc] || '') + ' ' + (_scopeNames[_sc] || _scopoInfo) + '</span></div>';
    }
    html += '</div>';

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

    var _msgOutreach = (arricchito && dati.messaggio_personalizzato) ? dati.messaggio_personalizzato : (dati.messaggio_outreach || '');
    if (_msgOutreach) {
        var _titMsg = arricchito ? '&#9993; Messaggio Personalizzato' : 'Messaggio di Outreach';
        html += '<div class="report-sezione outreach-editor-section">' +
            '<h4>' + _titMsg + '</h4>' +
            '<textarea id="outreach-editor" class="outreach-textarea" rows="5">' + escHtml(_msgOutreach) + '</textarea>' +
            '<div class="outreach-actions">' +
                '<button class="btn btn-outline btn-sm" onclick="_copiaOutreach()"><span id="outreach-copia-label">Copia</span></button>' +
                '<button class="btn btn-outline btn-sm" onclick="_rigeneraOutreach()">Rigenera</button>' +
                '<button class="btn btn-sm" style="background:#f0fdf4;color:#16a34a;border:1px solid #86efac;" onclick="_salvaOutreach()"><span id="outreach-salva-label">Salva</span></button>' +
                '<span id="outreach-autosave-indicator" style="font-size:0.75rem;color:#9ca3af;margin-left:auto;display:none;">Salvato</span>' +
            '</div>' +
            '<div class="outreach-modifica">' +
                '<label style="font-size:0.82rem;font-weight:600;color:var(--testo);">Chiedi una modifica o variante:</label>' +
                '<textarea id="outreach-prompt-modifica" class="outreach-textarea" rows="2" ' +
                    'placeholder="Es: \'Rendilo pi\u00f9 breve e informale\' oppure \'Aggiungi un riferimento al suo ultimo post LinkedIn\'"></textarea>' +
                '<button class="btn btn-primary btn-sm" onclick="_applicaModificaOutreach()"><span id="outreach-modifica-label">Applica modifica</span></button>' +
            '</div>' +
            '<div id="outreach-versioni-wrap" style="display:none;margin-top:0.75rem;">' +
                '<details><summary style="font-size:0.8rem;color:var(--grigio-testo);cursor:pointer;font-weight:600;">Versioni precedenti</summary>' +
                '<div id="outreach-versioni-list" style="margin-top:0.5rem;"></div></details>' +
            '</div>' +
        '</div>';
    }

    // Bottone analisi approfondita (solo se non ancora arricchito e abbiamo il contesto)
    if (!arricchito && _reportGlobale && _reportGlobale.candidatoInfo) {
        html += '<div id="btn-approfondita-container" style="margin-top:1.25rem;padding-top:1rem;border-top:1px solid var(--grigio-bordo);">' +
            '<button onclick="_lanciaAnalisiApprofondita()" ' +
            'style="background:var(--azzurro);color:#fff;border:none;border-radius:var(--radius);' +
            'padding:0.6rem 1.25rem;font-size:0.9rem;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:0.5rem;">' +
            '⭐ Lancia Analisi Approfondita</button>' +
            '<p style="margin:0.5rem 0 0;font-size:0.8rem;color:var(--grigio-testo);">Arricchisce il profilo con dati LinkedIn tramite EnrichLayer</p>' +
            '</div>';
    }

    if (bodyEl) bodyEl.innerHTML = html;
    mostra('modal-report');
}

/**
 * Lancia l'analisi approfondita SSE sul candidato corrente nel modal.
 * Usa _reportGlobale.candidatoInfo per i dati del profilo.
 */
function _lanciaAnalisiApprofondita() {
    if (!_reportGlobale || !_reportGlobale.candidatoInfo) return;
    var ci = _reportGlobale.candidatoInfo;

    // Mostra spinner nel modal
    var streamEl = document.getElementById('modal-report-streaming');
    var bodyEl   = document.getElementById('modal-report-body');
    var savedEl  = document.getElementById('modal-report-saved');
    var spinnerEl = document.getElementById('modal-report-spinner');
    var statusEl  = document.getElementById('modal-report-status');
    var streamTextEl = document.getElementById('modal-report-stream-text');

    if (streamEl)    { streamEl.classList.remove('hidden'); }
    if (bodyEl)      { bodyEl.classList.add('hidden'); bodyEl.innerHTML = ''; }
    if (savedEl)     { savedEl.classList.add('hidden'); }
    if (spinnerEl)   { spinnerEl.style.display = ''; }
    if (statusEl)    { statusEl.innerHTML = '&#11088; Arricchimento con EnrichLayer in corso...'; }
    if (streamTextEl){ streamTextEl.textContent = ''; }

    fetch('/valutazione/analizza_stream', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            testo_profilo: ci.testo    || '',
            tipo_profilo:  ci.tipo     || 'A',
            linkedin_url:  ci.linkedin || null,
        })
    })
    .then(function(response) {
        var reader  = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer  = '';

        function read() {
            return reader.read().then(function(result) {
                if (result.done) return;
                buffer += decoder.decode(result.value, {stream: true});
                var lines = buffer.split('\n');
                buffer = lines.pop();

                lines.forEach(function(line) {
                    if (!line.startsWith('data: ')) return;
                    var dataStr = line.slice(6).trim();
                    if (!dataStr) return;
                    try {
                        var ev = JSON.parse(dataStr);
                        if (ev.type === 'chunk') {
                            if (streamTextEl) {
                                streamTextEl.textContent += ev.text || '';
                                streamTextEl.scrollTop = streamTextEl.scrollHeight;
                            }
                        } else if (ev.type === 'arricchimento_start') {
                            if (statusEl) statusEl.innerHTML = '&#11088; Arricchimento con dati LinkedIn in corso...';
                        } else if (ev.type === 'done') {
                            _mostraReportNelModal(ev.risultato, ci, _reportGlobale.salvaCallback);
                            if (_reportGlobale && _reportGlobale.salvaCallback) {
                                _reportGlobale.salvaCallback(ev.risultato);
                            }
                        } else if (ev.type === 'errore') {
                            if (spinnerEl) spinnerEl.style.display = 'none';
                            if (statusEl)  statusEl.textContent = 'Errore: ' + (ev.messaggio || 'sconosciuto');
                        }
                    } catch(e) {
                        console.error('[SSE approfondita]', e.message, '| line:', line.slice(0, 80));
                    }
                });
                return read();
            });
        }
        return read();
    })
    .catch(function(err) {
        if (spinnerEl) spinnerEl.style.display = 'none';
        if (statusEl)  statusEl.textContent = 'Errore di connessione: ' + err;
    });
}

/* ------------------------------------------------------------------ */
/* Editor Messaggio Outreach                                            */
/* ------------------------------------------------------------------ */
var _outreachVersioni = [];
var _outreachDebounceTimer = null;

function _outreachSetupAutosave() {
    var editor = document.getElementById('outreach-editor');
    if (!editor) return;
    editor.addEventListener('input', function() {
        clearTimeout(_outreachDebounceTimer);
        var indicator = document.getElementById('outreach-autosave-indicator');
        if (indicator) { indicator.style.display = 'none'; }
        _outreachDebounceTimer = setTimeout(function() {
            _salvaOutreach(true);
        }, 2000);
    });
}

// Osserva il modal per attaccare l'autosave quando il contenuto viene renderizzato
var _outreachObserver = new MutationObserver(function() {
    if (document.getElementById('outreach-editor')) {
        _outreachSetupAutosave();
    }
});
var _reportBody = document.getElementById('modal-report-body');
if (_reportBody) _outreachObserver.observe(_reportBody, { childList: true });

function _copiaOutreach() {
    var editor = document.getElementById('outreach-editor');
    if (!editor) return;
    navigator.clipboard.writeText(editor.value).then(function() {
        var label = document.getElementById('outreach-copia-label');
        label.textContent = 'Copiato \u2713';
        setTimeout(function() { label.textContent = 'Copia'; }, 2000);
    });
}

function _pushVersione(testo) {
    if (!testo || !testo.trim()) return;
    _outreachVersioni.push(testo.trim());
    var wrap = document.getElementById('outreach-versioni-wrap');
    var list = document.getElementById('outreach-versioni-list');
    if (!wrap || !list) return;
    wrap.style.display = '';
    var idx = _outreachVersioni.length - 1;
    var div = document.createElement('div');
    div.className = 'outreach-versione-item';
    div.innerHTML = '<div class="outreach-versione-header">' +
        '<span style="font-size:0.75rem;color:var(--grigio-testo);">v' + (idx + 1) + '</span>' +
        '<button class="btn btn-outline btn-xs" onclick="_ripristinaVersione(' + idx + ')">Usa questa</button></div>' +
        '<div class="outreach-versione-text">' + escHtml(testo.trim()) + '</div>';
    list.insertBefore(div, list.firstChild);
}

function _ripristinaVersione(idx) {
    var editor = document.getElementById('outreach-editor');
    if (!editor || idx >= _outreachVersioni.length) return;
    var corrente = editor.value.trim();
    if (corrente && corrente !== _outreachVersioni[idx]) {
        _pushVersione(corrente);
    }
    editor.value = _outreachVersioni[idx];
}

function _rigeneraOutreach() {
    var editor = document.getElementById('outreach-editor');
    if (!editor || !_reportGlobale || !_reportGlobale.candidatoInfo) return;
    var corrente = editor.value.trim();
    _pushVersione(corrente);

    var btn = editor.closest('.outreach-editor-section').querySelector('button:nth-child(2)');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }

    fetch('/valutazione/rigenera_messaggio', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            testo_profilo: _reportGlobale.candidatoInfo.testo || '',
            messaggio_attuale: corrente,
            istruzioni: ''
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.messaggio) {
            editor.value = data.messaggio;
        } else {
            alert('Errore: ' + (data.errore || 'risposta vuota'));
        }
    })
    .catch(function(err) { alert('Errore: ' + err); })
    .finally(function() {
        if (btn) { btn.disabled = false; btn.textContent = 'Rigenera'; }
    });
}

function _salvaOutreach(silent) {
    var editor = document.getElementById('outreach-editor');
    if (!editor || !_reportGlobale || !_reportGlobale.candidatoInfo) return;
    var ci = _reportGlobale.candidatoInfo;
    var candidatoId = ci.candidato_id || null;
    if (!candidatoId) {
        if (!silent) {
            var indicator = document.getElementById('outreach-autosave-indicator');
            if (indicator) { indicator.textContent = 'Nessun candidato associato'; indicator.style.display = ''; }
        }
        return;
    }

    fetch('/ricerca/salva-messaggio', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            candidato_id: candidatoId,
            messaggio: editor.value.trim()
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var indicator = document.getElementById('outreach-autosave-indicator');
        if (data.ok && indicator) {
            indicator.textContent = silent ? 'Salvato \u2713' : 'Salvato \u2713';
            indicator.style.display = '';
            var label = document.getElementById('outreach-salva-label');
            if (!silent && label) {
                label.textContent = 'Salvato \u2713';
                setTimeout(function() { label.textContent = 'Salva'; }, 2000);
            }
            setTimeout(function() { indicator.style.display = 'none'; }, 3000);
        }
    })
    .catch(function(err) { console.error('[salva outreach]', err); });
}

function _applicaModificaOutreach() {
    var editor = document.getElementById('outreach-editor');
    var promptEl = document.getElementById('outreach-prompt-modifica');
    if (!editor || !promptEl) return;
    var istruzioni = promptEl.value.trim();
    if (!istruzioni) { alert('Scrivi le istruzioni di modifica.'); return; }

    var corrente = editor.value.trim();
    _pushVersione(corrente);

    var labelEl = document.getElementById('outreach-modifica-label');
    var btnEl = labelEl ? labelEl.closest('button') : null;
    if (btnEl) { btnEl.disabled = true; }
    if (labelEl) { labelEl.innerHTML = '<span class="spinner"></span> Generazione...'; }

    fetch('/valutazione/rigenera_messaggio', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            testo_profilo: (_reportGlobale && _reportGlobale.candidatoInfo) ? _reportGlobale.candidatoInfo.testo || '' : '',
            messaggio_attuale: corrente,
            istruzioni: istruzioni
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.messaggio) {
            editor.value = data.messaggio;
            promptEl.value = '';
        } else {
            alert('Errore: ' + (data.errore || 'risposta vuota'));
        }
    })
    .catch(function(err) { alert('Errore: ' + err); })
    .finally(function() {
        if (btnEl) { btnEl.disabled = false; }
        if (labelEl) { labelEl.textContent = 'Applica modifica'; }
    });
}
