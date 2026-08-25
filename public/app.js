document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn      = document.getElementById('toggle-direction');
    const dirLabel       = document.getElementById('dir-label');
    const sourceText     = document.getElementById('source-text');
    const targetText     = document.getElementById('target-text');
    const translateBtn   = document.getElementById('translate-btn');
    const clearBtn       = document.getElementById('clear-btn');
    const copyBtn        = document.getElementById('copy-btn');
    const spinner        = document.getElementById('loading-spinner');
    const btnText        = translateBtn.querySelector('span');
    const diagContainer  = document.getElementById('diagnostics-container');
    const diagList       = document.getElementById('diagnostics-list');
    const virtualKB      = document.getElementById('osm-keyboard');
    const dynamicKeys    = document.getElementById('dynamic-keys-container');
    const heroSpan       = document.getElementById('hero-osm');

    let currentDirection = 'to-osm';

    // ── Load dynamic hero text ───────────────────────────────────────────
    fetch('/api/hero-text')
        .then(r => r.json())
        .then(d => { heroSpan.textContent = d.osm; })
        .catch(() => { heroSpan.textContent = ''; });

    // ── Build virtual keyboard from API ──────────────────────────────────
    fetch('/api/keyboard-layout')
        .then(r => r.json())
        .then(data => {
            data.rows.forEach(({ label, keys }) => {
                const section = document.createElement('div');
                section.className = 'keyboard-section';

                const lbl = document.createElement('div');
                lbl.className = 'keyboard-label';
                lbl.textContent = label;
                section.appendChild(lbl);

                const row = document.createElement('div');
                row.className = 'keyboard-row';
                keys.forEach(char => {
                    const btn = document.createElement('button');
                    btn.className = 'key';
                    btn.textContent = char;
                    btn.addEventListener('click', e => insertChar(e, char));
                    row.appendChild(btn);
                });
                section.appendChild(row);
                dynamicKeys.appendChild(section);
            });
        })
        .catch(err => console.error('Failed to load keyboard layout', err));

    // ── Direction toggle ─────────────────────────────────────────────────
    toggleBtn.addEventListener('click', () => {
        toggleBtn.classList.toggle('flipped');
        if (currentDirection === 'to-osm') {
            currentDirection = 'from-osm';
            dirLabel.textContent = 'OSM → English';
            sourceText.placeholder = 'Enter or type OSM text…';
            sourceText.classList.add('osm-text');
            targetText.classList.remove('osm-text');
            virtualKB.style.display = 'flex';
        } else {
            currentDirection = 'to-osm';
            dirLabel.textContent = 'English → OSM';
            sourceText.placeholder = 'Enter text to translate…';
            sourceText.classList.remove('osm-text');
            targetText.classList.add('osm-text');
            virtualKB.style.display = 'none';
        }
        // Swap contents
        const temp = sourceText.value;
        sourceText.value = targetText.textContent;
        targetText.textContent = temp;
        diagContainer.style.display = 'none';
    });

    // ── Reset ────────────────────────────────────────────────────────────
    clearBtn.addEventListener('click', () => {
        sourceText.value = '';
        targetText.textContent = '';
        diagContainer.style.display = 'none';
        sourceText.focus();
    });

    // ── Copy ─────────────────────────────────────────────────────────────
    copyBtn.addEventListener('click', () => {
        if (!targetText.textContent) return;
        navigator.clipboard.writeText(targetText.textContent).then(() => {
            const original = copyBtn.innerHTML;
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24"><path fill="var(--accent)" d="M9,20.42L2.79,14.21L5.62,11.38L9,14.77L18.88,4.88L21.71,7.71L9,20.42Z"/></svg>';
            setTimeout(() => { copyBtn.innerHTML = original; }, 2000);
        });
    });

    // ── Keyboard input helpers ───────────────────────────────────────────
    function insertChar(e, char) {
        e.preventDefault();
        const s = sourceText.selectionStart;
        const end = sourceText.selectionEnd;
        const v = sourceText.value;
        sourceText.value = v.substring(0, s) + char + v.substring(end);
        sourceText.selectionStart = sourceText.selectionEnd = s + char.length;
        sourceText.focus();
    }

    // Action keys (Space, Backspace, Translate)
    document.querySelectorAll('.action-key').forEach(key => {
        key.addEventListener('click', e => {
            e.preventDefault();
            const action = key.dataset.action;
            const s = sourceText.selectionStart;
            const end = sourceText.selectionEnd;
            const v = sourceText.value;

            if (action === 'space') {
                sourceText.value = v.substring(0, s) + ' ' + v.substring(end);
                sourceText.selectionStart = sourceText.selectionEnd = s + 1;
                sourceText.focus();
            } else if (action === 'backspace') {
                if (s === end && s > 0) {
                    sourceText.value = v.substring(0, s - 1) + v.substring(end);
                    sourceText.selectionStart = sourceText.selectionEnd = s - 1;
                } else if (s !== end) {
                    sourceText.value = v.substring(0, s) + v.substring(end);
                    sourceText.selectionStart = sourceText.selectionEnd = s;
                }
                sourceText.focus();
            } else if (action === 'enter') {
                doTranslate();
            }
        });
    });

    // ── Enter key in textarea triggers translation ───────────────────────
    sourceText.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            doTranslate();
        }
    });

    // ── Translate button ─────────────────────────────────────────────────
    translateBtn.addEventListener('click', () => doTranslate());

    async function doTranslate() {
        const text = sourceText.value.trim();
        if (!text || translateBtn.disabled) return;

        translateBtn.disabled = true;
        btnText.style.display = 'none';
        spinner.style.display = 'block';
        targetText.textContent = 'Translating…';
        diagContainer.style.display = 'none';
        diagList.innerHTML = '';

        try {
            const res = await fetch('/api/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, direction: currentDirection }),
            });
            const data = await res.json();
            targetText.textContent = data.translated;

            if (data.diagnostics?.length) {
                diagContainer.style.display = 'block';
                data.diagnostics.forEach(note => {
                    const li = document.createElement('li');
                    li.textContent = note.trim();
                    diagList.appendChild(li);
                });
            }
        } catch (err) {
            targetText.textContent = 'Error connecting to the translation engine.';
            console.error('Translation error:', err);
        } finally {
            translateBtn.disabled = false;
            btnText.style.display = 'block';
            spinner.style.display = 'none';
        }
    }
});
