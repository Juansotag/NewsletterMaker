// ══════════════════════════════════════════════════════
// TABS
// ══════════════════════════════════════════════════════
function switchTab(tab) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`panel-${tab}`).classList.add('active');
  document.getElementById(`tab-${tab}-btn`).classList.add('active');
  if (tab === 'ctx') loadCtxFiles();
  if (tab === 'config') loadConfigTab();
  if (tab === 'hist') loadHistorial();
  if (tab === 'send') loadSchedules();
}

// ══════════════════════════════════════════════════════
// CHIPS — ejes temáticos
// ══════════════════════════════════════════════════════
document.getElementById('chips').addEventListener('click', e => {
  // Quitar chip personalizado
  if (e.target.classList.contains('chip-x')) {
    e.target.closest('.chip')?.remove();
    return;
  }
  // Toggle chip
  const chip = e.target.closest('.chip');
  if (!chip) return;
  const on = chip.getAttribute('aria-pressed') === 'true';
  chip.setAttribute('aria-pressed', String(!on));
});

document.getElementById('newEjeInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); addCustomEje(); }
});

function addCustomEje() {
  const input = document.getElementById('newEjeInput');
  const val = input.value.trim();
  if (!val) return;
  const chip = document.createElement('span');
  chip.className = 'chip';
  chip.setAttribute('aria-pressed', 'true');
  chip.dataset.eje = val;
  chip.innerHTML = `${esc(val)} <span class="chip-x" title="Quitar">×</span>`;
  document.getElementById('chips').appendChild(chip);
  input.value = '';
  input.focus();
}

// ══════════════════════════════════════════════════════
// CONFIG
// ══════════════════════════════════════════════════════
function getConfig() {
  const ejes = [...document.querySelectorAll('#chips .chip[aria-pressed=true]')].map(c => c.dataset.eje);
  const num = Math.max(1, Math.min(20, parseInt(document.getElementById('num').value, 10) || 4));
  return {
    tipo: document.getElementById('tipo').value,
    ejes,
    periodo_dias: Number(document.getElementById('periodo').value),
    num_items: num,
    audiencia: document.getElementById('audiencia').value,
    notas: document.getElementById('notas').value,
    buscar_web: true,
    usar_contexto: true
  };
}

// ══════════════════════════════════════════════════════
// GENERACIÓN CON STREAMING
// ══════════════════════════════════════════════════════
async function generar() {
  const cfg = getConfig();
  cfg.model = localStorage.getItem('claude_model_generation') || 'claude-sonnet-4-6';
  const btn = document.getElementById('generar');
  const label = document.getElementById('btnLabel');

  btn.disabled = true;
  label.innerHTML = '<span class="spinner"></span> Conectando…';
  showLiveLog();

  try {
    label.innerHTML = '<span class="spinner"></span> Buscando y redactando con Claude Sonnet…';

    const response = await fetch('/api/generate/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(cfg)
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.error || err.message || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let textLen = 0;
    let writingEl = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Procesar líneas SSE completas
      const lines = buffer.split('\n');
      buffer = lines.pop(); // línea incompleta queda en buffer

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }

        switch (evt.type) {
          case 'searching':
            addLog(`Búsqueda ${evt.count}…`, 'search');
            break;
          case 'search_query':
            addLog(`↳ «${esc(evt.query)}»`, 'query');
            break;
          case 'text_chunk':
            textLen = evt.total || textLen;
            if (!writingEl) {
              writingEl = addLog(`Redactando… (${textLen} car.)`, 'writing');
            } else {
              writingEl.textContent = `Redactando… (${textLen} car.)`;
            }
            break;
          case 'done':
            _currentReportId = evt.report_id || null;
            renderNewsletter(evt.newsletter);
            btn.disabled = false;
            label.textContent = 'Generar newsletter';
            return;
          case 'error':
            showError(evt.message);
            btn.disabled = false;
            label.textContent = 'Generar newsletter';
            return;
        }
      }
    }

  } catch (err) {
    if (err.message === 'Failed to fetch') {
      showError('No se pudo conectar con el backend en http://localhost:8000. ¿Está corriendo el servidor?');
    } else {
      showError(`Error: ${err.message}`);
    }
  }

  btn.disabled = false;
  label.textContent = 'Generar newsletter';
}

function showLiveLog() {
  document.getElementById('output').innerHTML = `
<div class="live-log">
  <div class="log-header">
    <span class="log-pulse"></span>
    <span>El LLM está buscando y redactando tu newsletter…</span>
  </div>
  <div class="log-entries" id="logEntries"></div>
</div>`;
}

function addLog(html, cls = '') {
  const entries = document.getElementById('logEntries');
  if (!entries) return null;
  const div = document.createElement('div');
  div.className = `log-entry ${cls}`.trim();
  div.innerHTML = html;
  entries.appendChild(div);
  entries.scrollTop = entries.scrollHeight;
  return div;
}

function showError(msg) {
  document.getElementById('output').innerHTML = `
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:260px;gap:1rem;padding:2rem;text-align:center;">
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#d51437" stroke-width="1.5">
    <circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>
  </svg>
  <p style="color:#d51437;font-weight:600;margin:0;max-width:380px;">${esc(msg)}</p>
  <button class="btn-ghost" onclick="resetOutput()">Volver</button>
</div>`;
}

function resetOutput() {
  document.getElementById('output').innerHTML = `
<div class="empty" id="emptyState">
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>
  </svg>
  <div>Tu newsletter aparecerá aquí.<br>Configura a la izquierda y pulsa <b>Generar</b>.</div>
</div>`;
}

function formatUrl(url) {
  if (!url) return '';
  url = String(url).trim();
  if (url === '#' || url === '' || url.toLowerCase() === 'null' || url.toLowerCase() === 'undefined') return '';
  if (!/^https?:\/\//i.test(url)) {
    return 'https://' + url;
  }
  return url;
}

// ══════════════════════════════════════════════════════
// RENDER NEWSLETTER
// ══════════════════════════════════════════════════════
function renderNewsletter(d) {
  const out = document.getElementById('output');

  // Cifras
  let cifrasHtml = '';
  if (d.cifras && d.cifras.length) {
    const cards = d.cifras.map(c => {
      const u = formatUrl(c.url);
      return `
  <div class="cifra-card">
    <div class="cifra-dato">${esc(c.dato)}</div>
    <div class="cifra-ctx">${esc(c.contexto || '')}</div>
    ${u
        ? `<div class="cifra-src"><a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-dark);font-weight:600;text-decoration:underline;">${esc(c.fuente || 'Ver fuente')} ↗</a>${c.fecha_publicacion ? ` · <span style="font-weight:500;opacity:0.85;">${esc(c.fecha_publicacion)}</span>` : ''}</div>`
        : c.fuente ? `<div class="cifra-src">${esc(c.fuente)}${c.fecha_publicacion ? ` · <span style="font-weight:500;opacity:0.85;">${esc(c.fecha_publicacion)}</span>` : ''}</div>` : ''}
  </div>`;
    }).join('');
    cifrasHtml = `
  <div class="nl-cifras">
    <p class="nl-cifras-title">Cifras importantes del sector</p>
    <div class="cifras-grid">${cards}</div>
  </div>`;
  }

  // Ítems
  const itemsHtml = (d.items || []).map(it => {
    const u = formatUrl(it.url);
    const titleHtml = u
      ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-dark);text-decoration:none;">${esc(it.titular || '')}</a>`
      : esc(it.titular || '');
    const srcHtml = u
      ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-light);font-weight:600;text-decoration:underline;">${esc(it.fuente || 'Ver enlace')} ↗</a>`
      : esc(it.fuente || '—');

    return `
<div class="nl-item">
  ${it.eje ? `<div class="nl-eje">${esc(it.eje)}</div>` : ''}
  <h3>${titleHtml}</h3>
  <p>${esc(it.resumen || '')}</p>
  ${it.por_que_importa ? `<div class="nl-why"><b>Por qué importa:</b> ${esc(it.por_que_importa)}</div>` : ''}
  <p class="nl-src">Fuente: ${srcHtml}${it.fecha_publicacion ? ` · <span style="color:var(--text-muted);font-weight:500;">📅 ${esc(it.fecha_publicacion)}</span>` : ''}</p>
</div>`;
  }).join('');

  // Oportunidades
  const oppsHtml = (d.oportunidades && d.oportunidades.length) ? `
<div class="nl-opps">
  <h4>Oportunidades accionables</h4>
  <ul>${d.oportunidades.map(o => {
    if (typeof o === 'string') return `<li>${esc(o)}</li>`;
    const u = formatUrl(o.url);
    const src = u
      ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-light);font-weight:600;text-decoration:underline;">${esc(o.fuente || 'Ver convocatoria')} ↗</a>`
      : o.fuente ? esc(o.fuente) : '';
    return `<li>${esc(o.texto || o.text || '')}${src ? ` <span class="nl-opp-src">— ${src}</span>` : ''}</li>`;
  }).join('')}</ul>
</div>` : '';

  out.innerHTML = `
<div class="toolbar">
  <span></span>
  <button class="btn-ghost" onclick="downloadPDF('output', this)">Descargar PDF</button>
</div>
<div class="nl-head">
  <div class="nl-kicker">Universidad de La Sabana</div>
  <div class="nl-title">${esc(d.titulo || 'Newsletter Ejecutivo')}</div>
  <div class="nl-meta">${esc(d.fecha || '')}${d.contexto ? ' - ' + esc(d.contexto) : ''}</div>
</div>
${cifrasHtml}
${itemsHtml}
${oppsHtml}`;
}

// ══════════════════════════════════════════════════════
// CONTEXT EDITOR
// ══════════════════════════════════════════════════════
let _ctxCurrentFile = null;

// ══════════════════════════════════════════════════════
// EDITOR DE CONTEXTO (SUPABASE CRUD)
// ══════════════════════════════════════════════════════
let _docsList = []; // Array containing all documents metadata
let _ctxCurrentFileId = null;
let _currentDocOriginal = null;

async function loadCtxFiles() {
  const container = document.getElementById('fileList');
  container.innerHTML = '<li style="color:var(--text-muted);font-size:.85rem;padding:.4rem;">Cargando…</li>';
  try {
    const r = await fetch('/api/docs');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { files } = await r.json();
    _docsList = files;

    renderFileTree();
  } catch (e) {
    container.innerHTML = `<li style="color:var(--c-red);font-size:.85rem;padding:.4rem;">${esc(e.message)}</li>`;
  }
}

const _collapsedFolders = {};

function renderFileTree() {
  const container = document.getElementById('fileList');
  if (!container) return;

  if (!_docsList.length) {
    container.innerHTML = '<li style="color:var(--text-muted);font-size:.85rem;padding:.4rem;">No hay archivos.</li>';
    return;
  }

  const folders = {};
  _docsList.forEach(doc => {
    const f = doc.folder || '';
    if (!folders[f]) folders[f] = [];
    folders[f].push(doc);
  });

  const sortedFolderNames = Object.keys(folders).sort((a, b) => {
    if (a === '') return -1;
    if (b === '') return 1;
    return a.localeCompare(b);
  });

  let html = '';
  sortedFolderNames.forEach(folder => {
    const docs = folders[folder];
    const folderLabel = folder || 'Raíz (/)';
    const isCollapsed = _collapsedFolders[folder] === true;
    const displayStyle = isCollapsed ? 'none' : 'block';
    const arrow = isCollapsed ? '▶' : '▼';

    html += `
      <li style="margin-bottom: 0.5rem; list-style: none;">
        <div onclick="toggleFolder('${esc(folder)}')" style="display: flex; align-items: center; gap: 0.4rem; padding: 0.4rem; font-weight: 700; font-size: 0.85rem; color: var(--c-blue-dark); cursor: pointer; user-select: none;">
          <span style="font-size: 0.65rem; color: var(--text-muted); width: 10px; display: inline-block;">${arrow}</span>
          <span>${esc(folderLabel)}</span>
        </div>
        <ul id="folder-group-${esc(folder).replace(/\W/g, '_')}" style="display: ${displayStyle}; list-style: none; padding-left: 1rem; margin: 0; border-left: 1px dashed var(--border-color);">
    `;

    docs.sort((a, b) => a.sort_order - b.sort_order);

    docs.forEach(f => {
      const isActive = _ctxCurrentFileId === f.id;
      const systemBadge = f.is_system_prompt ? ' <span style="font-size: 0.65rem; background: var(--c-blue-tint); color: var(--c-blue-light); padding: 0.1rem 0.35rem; border-radius: 4px; font-weight: 700;">PROMPT</span>' : '';
      html += `
        <li class="file-item${isActive ? ' active' : ''}" 
            id="fi-${f.id}" 
            onclick="loadCtxFile('${f.id}')"
            style="padding: 0.45rem 0.65rem; font-size: 0.82rem; margin-top: 0.15rem; display: flex; align-items: center; justify-content: space-between; border-radius: 6px; cursor: pointer;">
          <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${esc(f.name)}${systemBadge}</span>
        </li>
      `;
    });

    html += `
        </ul>
      </li>
    `;
  });

  container.innerHTML = html;
}

function toggleFolder(folder) {
  _collapsedFolders[folder] = !_collapsedFolders[folder];
  renderFileTree();
}

async function loadCtxFile(id) {
  _ctxCurrentFileId = id;

  document.querySelectorAll('.file-item').forEach(el => el.classList.remove('active'));
  const activeEl = document.getElementById(`fi-${id}`);
  if (activeEl) activeEl.classList.add('active');

  const empty = document.getElementById('ctxEditorEmpty');
  const body = document.getElementById('ctxEditorBody');
  empty.style.display = 'none';
  body.style.display = 'none';
  document.getElementById('ctxEditorTitle').textContent = 'Cargando…';

  try {
    const r = await fetch(`/api/docs/${id}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const doc = await r.json();

    _currentDocOriginal = doc;

    document.getElementById('ctxEditorTitle').textContent = doc.name;
    document.getElementById('ctxFolderInput').value = doc.folder || '';
    document.getElementById('ctxNameInput').value = doc.name;
    document.getElementById('ctxDescInput').value = doc.description || '';
    document.getElementById('ctxTextarea').value = doc.content || '';

    const chatMsgs = document.getElementById('aiChatMessages');
    if (chatMsgs) {
      chatMsgs.innerHTML = `
        <div class="chat-msg ai">
          Hola, soy tu asistente de IA de GovLab. Puedo ayudarte a redactar o hacer cambios en el documento <strong>${esc(doc.name)}</strong>. Escribe tu instrucción abajo o presiona <strong>Guardar</strong> para validar los cambios automáticamente.
        </div>
      `;
    }

    const deleteBtn = document.getElementById('btnDeleteDoc');
    if (deleteBtn) {
      deleteBtn.style.display = doc.is_system_prompt ? 'none' : 'inline-block';
    }

    document.getElementById('ctxFolderInput').disabled = doc.is_system_prompt;
    document.getElementById('ctxNameInput').disabled = doc.is_system_prompt;

    switchEditorTab('edit');

    document.getElementById('savedBadge').classList.remove('show');
    body.style.display = 'block';
  } catch (e) {
    empty.textContent = `Error al cargar: ${e.message}`;
    empty.style.display = 'block';
  }
}

async function saveCtxFile() {
  if (!_ctxCurrentFileId) return;
  const folder = document.getElementById('ctxFolderInput').value.trim();
  const name = document.getElementById('ctxNameInput').value.trim();
  const description = document.getElementById('ctxDescInput').value.trim();
  const content = document.getElementById('ctxTextarea').value;

  if (!name) {
    alert('El nombre del archivo es obligatorio');
    return;
  }

  try {
    const r = await fetch(`/api/docs/${_ctxCurrentFileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder, name, description, content })
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${r.status}`);
    }

    const badge = document.getElementById('savedBadge');
    if (badge) {
      badge.classList.add('show');
      setTimeout(() => badge.classList.remove('show'), 3000);
    }

    await loadCtxFiles();
  } catch (e) {
    alert(`Error al guardar: ${e.message}`);
  }
}

async function createNewDocPrompt() {
  const name = prompt("Ingrese el nombre del nuevo documento (ej. '08_convocatorias.md'):");
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) {
    alert("El nombre no puede estar vacío");
    return;
  }

  try {
    const response = await fetch('/api/docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        folder: "",
        name: trimmed,
        content: `# ${trimmed}\n\nEscribe el contenido aquí...`,
        description: ""
      })
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${response.status}`);
    }

    const newDoc = await response.json();
    await loadCtxFiles();
    loadCtxFile(newDoc.id);
  } catch (e) {
    alert(`Error al crear documento: ${e.message}`);
  }
}

async function createNewFolderPrompt() {
  const folder = prompt("Nombre de la nueva carpeta (ej. 'perfiles'):");
  if (folder === null) return;
  const folderTrimmed = folder.trim();
  if (!folderTrimmed) {
    alert("El nombre de la carpeta no puede estar vacío");
    return;
  }

  const name = prompt(`Ingrese el nombre del primer documento para la carpeta '${folderTrimmed}':`, "01_documento.md");
  if (name === null) return;
  const nameTrimmed = name.trim();
  if (!nameTrimmed) {
    alert("El nombre del archivo no puede estar vacío");
    return;
  }

  try {
    const response = await fetch('/api/docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        folder: folderTrimmed,
        name: nameTrimmed,
        content: `# ${nameTrimmed}\n\nDocumento creado en la carpeta ${folderTrimmed}.`,
        description: ""
      })
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${response.status}`);
    }

    const newDoc = await response.json();
    await loadCtxFiles();
    loadCtxFile(newDoc.id);
  } catch (e) {
    alert(`Error al crear la carpeta: ${e.message}`);
  }
}

async function deleteCurrentDoc() {
  if (!_ctxCurrentFileId) return;
  if (!confirm(`¿Está seguro de que desea eliminar el documento '${_currentDocOriginal.name}'? Esta acción no se puede deshacer.`)) {
    return;
  }

  try {
    const response = await fetch(`/api/docs/${_ctxCurrentFileId}`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${response.status}`);
    }

    _ctxCurrentFileId = null;
    _currentDocOriginal = null;

    document.getElementById('ctxEditorBody').style.display = 'none';
    document.getElementById('ctxEditorEmpty').style.display = 'block';
    document.getElementById('ctxEditorEmpty').textContent = 'Selecciona un documento a la izquierda para editarlo.';

    await loadCtxFiles();
  } catch (e) {
    alert(`Error al eliminar: ${e.message}`);
  }
}

function updateMarkdownPreview() {
  const raw = document.getElementById('ctxTextarea').value;
  const previewEl = document.getElementById('ctxPreview');
  if (!previewEl || !window.marked) return;

  // Resaltar @referencias antes de parsear markdown
  const processed = raw.replace(
    /@([\w][\w\-\.]*\.md)/g,
    '<strong style="color:#1a3a6b;">@$1</strong>'
  );
  previewEl.innerHTML = window.marked.parse(processed);
}

function switchEditorTab(tab) {
  const textarea = document.getElementById('ctxTextarea');
  const previewContainer = document.getElementById('previewContainer');
  const editBtn = document.getElementById('editTabBtn');
  const previewBtn = document.getElementById('previewTabBtn');

  if (!textarea || !previewContainer || !editBtn || !previewBtn) return;

  if (tab === 'edit') {
    textarea.style.display = 'block';
    previewContainer.style.display = 'none';

    editBtn.style.borderBottom = '2px solid var(--c-blue-dark)';
    editBtn.style.color = 'var(--c-blue-dark)';
    editBtn.style.fontWeight = '700';

    previewBtn.style.borderBottom = 'none';
    previewBtn.style.color = 'var(--text-muted)';
    previewBtn.style.fontWeight = '600';
  } else {
    textarea.style.display = 'none';
    previewContainer.style.display = 'block';

    previewBtn.style.borderBottom = '2px solid var(--c-blue-dark)';
    previewBtn.style.color = 'var(--c-blue-dark)';
    previewBtn.style.fontWeight = '700';

    editBtn.style.borderBottom = 'none';
    editBtn.style.color = 'var(--text-muted)';
    editBtn.style.fontWeight = '600';

    updateMarkdownPreview();
  }
}

// ══════════════════════════════════════════════════════
// ASISTENTE DE IA & CHATBOT
// ══════════════════════════════════════════════════════
function toggleAiAssistant() {
  const panel = document.getElementById('aiAssistantPanel');
  const btn = document.getElementById('btnAiAssist');
  if (!panel) return;
  if (panel.style.display === 'none') {
    panel.style.display = 'flex';
    if (btn) btn.classList.add('active');
    const chatMsgs = document.getElementById('aiChatMessages');
    if (chatMsgs) chatMsgs.scrollTop = chatMsgs.scrollHeight;
    const input = document.getElementById('aiChatInput');
    if (input) input.focus();
  } else {
    panel.style.display = 'none';
    if (btn) btn.classList.remove('active');
  }
}

function appendChatMessage(sender, text, type = '') {
  const container = document.getElementById('aiChatMessages');
  if (!container) return null;

  const div = document.createElement('div');
  div.className = `chat-msg ${sender}`;

  if (type === 'warning') {
    div.style.background = '#FFF5F5';
    div.style.color = 'var(--c-red)';
    div.style.borderColor = '#FFC1C1';
    div.style.borderStyle = 'solid';
    div.style.borderWidth = '1px';
  } else if (type === 'success') {
    div.style.background = '#F0FFF4';
    div.style.color = 'var(--c-green)';
    div.style.borderColor = '#C6F6D5';
    div.style.borderStyle = 'solid';
    div.style.borderWidth = '1px';
  } else if (type === 'loading') {
    div.innerHTML = `<span class="spinner" style="border-top-color: var(--c-blue-dark); border-left-color: rgba(0,0,0,0.1); border-right-color: rgba(0,0,0,0.1); border-bottom-color: rgba(0,0,0,0.1);"></span> ${esc(text)}`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
  }

  div.innerHTML = text.replace(/\n/g, '<br>');
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

async function sendAiChatMessage() {
  if (!_ctxCurrentFileId) return;
  const input = document.getElementById('aiChatInput');
  const instruction = input.value.trim();
  if (!instruction) return;

  appendChatMessage('user', instruction);
  input.value = '';
  input.style.height = '38px';

  input.disabled = true;
  const sendBtn = document.getElementById('btnSendAiChat');
  if (sendBtn) sendBtn.disabled = true;

  const loadingMsg = appendChatMessage('ai', 'Procesando cambios...', 'loading');

  const content = document.getElementById('ctxTextarea').value;
  const name = document.getElementById('ctxNameInput').value;

  try {
    const model = localStorage.getItem('openai_model_assist') || 'gpt-4o';
    const r = await fetch('/api/docs/assist', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ name, content, instruction, model })
    });

    if (loadingMsg) loadingMsg.remove();

    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${r.status}`);
    }

    const data = await r.json();

    appendChatMessage('ai', data.response);

    if (data.modified_content !== content) {
      document.getElementById('ctxTextarea').value = data.modified_content;
      updateMarkdownPreview();
      appendChatMessage('ai', 'El documento ha sido modificado en el editor.', 'success');
    }
  } catch (e) {
    if (loadingMsg) loadingMsg.remove();
    appendChatMessage('ai', `Error: ${e.message}`, 'warning');
  } finally {
    input.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
    input.focus();
  }
}

function handleAiChatKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendAiChatMessage();
  }
}

async function saveCtxFileDirect(folder, name, description, content) {
  const saveBtn = document.querySelector('button[onclick="validateAndSaveCtxFile()"]');
  if (saveBtn) saveBtn.disabled = true;
  try {
    const saveResponse = await fetch(`/api/docs/${_ctxCurrentFileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder, name, description, content })
    });

    if (!saveResponse.ok) {
      const err = await saveResponse.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${saveResponse.status}`);
    }

    const badge = document.getElementById('savedBadge');
    if (badge) {
      badge.classList.add('show');
      setTimeout(() => badge.classList.remove('show'), 3000);
    }
    await loadCtxFiles();
  } catch (e) {
    alert(`Error al guardar: ${e.message}`);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function validateAndSaveCtxFile() {
  if (!_ctxCurrentFileId) return;

  const folder = document.getElementById('ctxFolderInput').value.trim();
  const name = document.getElementById('ctxNameInput').value.trim();
  const description = document.getElementById('ctxDescInput').value.trim();
  const content = document.getElementById('ctxTextarea').value;

  if (!name) {
    alert('El nombre del archivo es obligatorio');
    return;
  }

  const isSystemPrompt = _currentDocOriginal && _currentDocOriginal.is_system_prompt;
  if (isSystemPrompt) {
    const confirmSave = confirm(
      "Atención: Está guardando el Prompt del Sistema (00_sistema_instrucciones.md).\n\n" +
      "Le recomendamos consultar antes al Asistente de IA (Chatbot) para asegurarse de que el formato del JSON de salida no se haya roto.\n\n" +
      "¿Desea guardar los cambios directamente de todas formas?"
    );
    if (!confirmSave) {
      return;
    }
  }

  await saveCtxFileDirect(folder, name, description, content);
}

// ══════════════════════════════════════════════════════
// @ MENTION AUTOCOMPLETE — EDITOR DE CONTEXTO
// ══════════════════════════════════════════════════════
let _atActive = false;
let _atQuery = '';
let _atStart = -1;   // posición del @ en el textarea
let _atSelIdx = 0;

/** Documentos filtrados, excluyendo el doc actual (referencia circular) */
function _atFilterDocs(query) {
  const curName = _currentDocOriginal ? _currentDocOriginal.name : null;
  const q = query.toLowerCase();
  return _docsList.filter(d => {
    if (d.is_system_prompt) return false;
    if (d.name === curName) return false;   // evitar referencia circular
    if (!q) return true;
    return d.name.toLowerCase().includes(q) ||
      (d.folder || '').toLowerCase().includes(q);
  });
}

/** Renderiza los ítems del dropdown */
function _atRender() {
  const dd = document.getElementById('atMentionDropdown');
  if (!dd) return;
  const items = _atFilterDocs(_atQuery);

  if (!items.length) {
    dd.innerHTML =
      '<div class="at-mention-header">Referenciar documento</div>' +
      '<div class="at-mention-empty">Sin coincidencias</div>';
    return;
  }

  dd.innerHTML =
    '<div class="at-mention-header">Referenciar documento</div>' +
    items.map((d, i) => {
      const isActive = i === _atSelIdx;
      const folder = d.folder ? `<span class="at-mention-folder">· ${esc(d.folder)}</span>` : '';
      return `<div class="at-mention-item${isActive ? ' at-active' : ''}"
        onmousedown="event.preventDefault(); _atConfirm(${i})"
        onmouseover="_atSelIdx=${i}; _atRender()">
        <span class="at-mention-icon">@</span>
        <span>
          <span class="at-mention-name">${esc(d.name)}</span>${folder}
        </span>
      </div>`;
    }).join('');

  // Asegurar que el ítem activo sea visible
  const active = dd.querySelector('.at-active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

/** Posiciona el dropdown en relación al cursor del textarea */
function _atPosition() {
  const ta = document.getElementById('ctxTextarea');
  const dd = document.getElementById('atMentionDropdown');
  if (!ta || !dd) return;

  const style = getComputedStyle(ta);
  const lineHeight = parseFloat(style.lineHeight) || 21;
  const paddingTop = parseFloat(style.paddingTop) || 12;

  // Contar líneas hasta el cursor para aproximar Y
  const textBefore = ta.value.substring(0, _atStart + 1);
  const lines = textBefore.split('\n');
  const lineIdx = lines.length - 1;
  const approxTop = paddingTop + lineIdx * lineHeight - ta.scrollTop + lineHeight + 4;

  // Aproximar X con la longitud de la última línea
  const charWidth = 7.6; // ~0.82rem monospace
  const lastLine = lines[lines.length - 1];
  const approxLeft = Math.min(lastLine.length * charWidth, ta.offsetWidth - 290);

  dd.style.top = Math.max(4, approxTop) + 'px';
  dd.style.left = Math.max(0, approxLeft) + 'px';
}

function _atShow() {
  const dd = document.getElementById('atMentionDropdown');
  if (!dd) return;
  _atPosition();
  dd.style.display = 'block';
  _atRender();
}

function _atHide() {
  const dd = document.getElementById('atMentionDropdown');
  if (dd) {
    dd.style.display = 'none';
    dd.innerHTML = '<div class="at-mention-header">Referenciar documento</div>';
  }
  _atActive = false;
  _atStart = -1;
  _atQuery = '';
  _atSelIdx = 0;
}

/** Inserta @nombre_doc.md en el textarea y cierra el dropdown */
function _atConfirm(idx) {
  const items = _atFilterDocs(_atQuery);
  if (!items[idx]) return;
  const ta = document.getElementById('ctxTextarea');
  const before = ta.value.substring(0, _atStart);
  const after = ta.value.substring(_atStart + 1 + _atQuery.length);
  const inserted = '@' + items[idx].name;
  ta.value = before + inserted + after;
  const newPos = _atStart + inserted.length;
  ta.setSelectionRange(newPos, newPos);
  ta.focus();
  updateMarkdownPreview();
  _atHide();
}

/** Handler para el evento input del textarea */
function _atHandleInput() {
  const ta = document.getElementById('ctxTextarea');
  const pos = ta.selectionStart;
  const val = ta.value;

  // Buscar @ hacia atrás desde el cursor sin cruzar newlines
  let atPos = -1;
  for (let i = pos - 1; i >= 0; i--) {
    const chatCh = val[i];
    if (chatCh === '@') { atPos = i; break; }
    if (chatCh === '\n' || chatCh === '\r') break;
    // Solo caracteres válidos en nombre de archivo entre @ y cursor
    if (!/[\w\-\.]/.test(chatCh)) break;
  }

  if (atPos === -1) { if (_atActive) _atHide(); return; }

  const query = val.substring(atPos + 1, pos);
  // Rechazar si hay caracteres no válidos en el query
  if (/[^\w\-\.]/.test(query)) { _atHide(); return; }

  _atActive = true;
  _atStart = atPos;
  _atQuery = query;
  _atSelIdx = 0;
  _atShow();
}

/** Handler para keydown: navegación y confirmación con teclado */
function _atHandleKeydown(e) {
  if (!_atActive) return;
  const items = _atFilterDocs(_atQuery);
  const len = items.length;

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _atSelIdx = len ? (_atSelIdx + 1) % len : 0;
    _atRender();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _atSelIdx = len ? (_atSelIdx - 1 + len) % len : 0;
    _atRender();
  } else if ((e.key === 'Enter' || e.key === 'Tab') && len) {
    e.preventDefault();
    _atConfirm(_atSelIdx);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    _atHide();
  }
}

// Conectar eventos al textarea cuando el DOM está listo
; (function initAtMention() {
  const ta = document.getElementById('ctxTextarea');
  if (!ta) return;
  ta.addEventListener('input', _atHandleInput);
  ta.addEventListener('keydown', _atHandleKeydown);
  // Ocultar al hacer scroll para reposicionar si es necesario
  ta.addEventListener('scroll', function () { if (_atActive) _atPosition(); });
})();

// Cerrar dropdown al hacer clic fuera del textarea y del dropdown
document.addEventListener('mousedown', function (e) {
  const dd = document.getElementById('atMentionDropdown');
  if (!dd || !_atActive) return;
  if (!dd.contains(e.target) && e.target.id !== 'ctxTextarea') {
    _atHide();
  }
});

// ══════════════════════════════════════════════════════
// ENVÍO PROGRAMADO — SCHEDULES
// ══════════════════════════════════════════════════════

/** Muestra/oculta el input de cron personalizado según el preset */
function _syncCronInput() {
  const preset = document.getElementById('sendFreqPreset').value;
  const row = document.getElementById('sendCronCustomRow');
  if (row) row.style.display = preset === 'custom' ? 'block' : 'none';
}

/** Retorna la expresión cron activa según el preset o el campo custom */
function _activeCron() {
  const preset = document.getElementById('sendFreqPreset').value;
  if (preset === 'custom') return (document.getElementById('sendCron').value || '').trim();
  return preset;
}

/** Carga y renderiza la lista de schedules */
async function loadSchedules() {
  const list = document.getElementById('scheduleList');
  if (!list) return;
  list.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem;">Cargando…</p>';
  try {
    const r = await fetch('/api/schedules');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { schedules } = await r.json();
    renderScheduleList(schedules);
  } catch (e) {
    list.innerHTML = `<p style="color:var(--c-red);font-size:.82rem;">Error: ${esc(e.message)}</p>`;
  }
}

/** Renderiza las tarjetas de cada schedule */
function renderScheduleList(schedules) {
  const list = document.getElementById('scheduleList');
  if (!list) return;
  if (!schedules || !schedules.length) {
    list.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem;">No hay programaciones activas.</p>';
    return;
  }
  list.innerHTML = schedules.map(s => {
    const lastRun = s.last_run ? _fmtDate(s.last_run) : 'Nunca';
    const nextRun = s.next_run ? _fmtDate(s.next_run) : '—';
    const badge = s.active
      ? '<span style="background:#e6f4ea;color:#1b7a3c;font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:20px;">Activo</span>'
      : '<span style="background:#fce8e8;color:#b42f2f;font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:20px;">Pausado</span>';
    const target = s.whatsapp_to || s.email_to || 'Sin destino';
    return `<div style="border:1px solid var(--border-color);border-radius:10px;padding:1rem 1.1rem;margin-bottom:.65rem;background:#fff;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;">
        <div style="flex:1;min-width:0;">
          <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;">
            <span style="font-weight:700;font-size:.88rem;color:var(--c-blue-dark);">${esc(s.name)}</span>
            ${badge}
          </div>
          <div style="font-size:.76rem;color:var(--text-muted);margin-top:.3rem;">
            📱 WhatsApp: <b>${esc(target)}</b> · ${esc(_humanizeCron(s.cron))}
          </div>
          <div style="font-size:.73rem;color:var(--text-muted);margin-top:.2rem;">
            Último envío: ${lastRun} · Próximo: ${nextRun}
          </div>
        </div>
      </div>
      <div style="display:flex;gap:.5rem;margin-top:.75rem;flex-wrap:wrap;">
        <button class="btn" onclick="runScheduleNow('${s.id}', this)"
                style="font-size:.78rem;padding:.35rem .8rem;">Enviar ahora</button>
        <button class="btn-ghost" onclick="toggleScheduleItem('${s.id}')"
                style="font-size:.78rem;padding:.35rem .7rem;">${s.active ? 'Pausar' : 'Activar'}</button>
        <button class="btn-ghost" onclick="deleteScheduleItem('${s.id}')"
                style="font-size:.78rem;padding:.35rem .7rem;border-color:var(--c-red);color:var(--c-red);">Eliminar</button>
      </div>
      <div id="sched-status-${s.id}" style="font-size:.78rem;margin-top:.4rem;"></div>
    </div>`;
  }).join('');
}

/** Construye el payload de config para el schedule a partir del formulario */
function _buildScheduleConfig() {
  return {
    tipo: 'ejecutivo',
    ejes: [],
    periodo_dias: parseInt(document.getElementById('sendPeriodo').value) || 7,
    num_items: parseInt(document.getElementById('sendNumItems').value) || 4,
    audiencia: document.getElementById('sendAudiencia').value.trim() || 'Juan Carlos Camelo',
    notas: '',
    model: document.getElementById('sendModel').value || 'gpt-4o',
    buscar_web: document.getElementById('sendBuscarWeb').checked,
    usar_contexto: true,
  };
}

/** Crea una nueva programación */
async function createSchedule() {
  const name = document.getElementById('sendName').value.trim();
  const target = document.getElementById('sendEmail').value.trim();
  const cron = _activeCron();
  const statusEl = document.getElementById('sendCreateStatus');
  const btn = document.getElementById('btnCreateSchedule');

  if (!name) { statusEl.style.color = 'var(--c-red)'; statusEl.textContent = 'Falta el nombre de la programación.'; return; }
  if (!target) { statusEl.style.color = 'var(--c-red)'; statusEl.textContent = 'Falta el número o grupo de WhatsApp destino.'; return; }
  if (!cron) { statusEl.style.color = 'var(--c-red)'; statusEl.textContent = 'Falta la expresión cron.'; return; }

  btn.disabled = true;
  statusEl.style.color = 'var(--text-muted)';
  statusEl.textContent = 'Creando…';

  try {
    const r = await fetch('/api/schedules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, whatsapp_to: target, email_to: target, cron, config: _buildScheduleConfig() }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${r.status}`);
    }
    statusEl.style.color = 'var(--c-green)';
    statusEl.textContent = '✓ Programación creada para WhatsApp.';
    document.getElementById('sendName').value = '';
    document.getElementById('sendEmail').value = '';
    await loadSchedules();
  } catch (e) {
    statusEl.style.color = 'var(--c-red)';
    statusEl.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

/** Dispara una generación + envío en segundo plano para el schedule dado y sondea su progreso */
async function runScheduleNow(id, btn) {
  const statusEl = document.getElementById(`sched-status-${id}`);
  if (btn) btn.disabled = true;
  if (statusEl) {
    statusEl.style.color = 'var(--text-muted)';
    statusEl.textContent = 'Iniciando proceso en el servidor…';
  }

  try {
    const response = await fetch(`/api/schedules/${id}/run`, {
      method: 'POST',
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `Error HTTP ${response.status}`);
    }

    if (statusEl) {
      statusEl.style.color = 'var(--text-muted)';
      statusEl.textContent = 'Conectando con Claude Sonnet…';
    }

    // Sondear estado periódicamente
    const startTime = Date.now();
    const pollInterval = setInterval(async () => {
      try {
        // Timeout de seguridad: 4 minutos
        if (Date.now() - startTime > 240000) {
          clearInterval(pollInterval);
          if (btn) btn.disabled = false;
          if (statusEl) {
            statusEl.style.color = 'var(--c-yellow)';
            statusEl.textContent = 'El proceso continúa ejecutándose en segundo plano. Revisa el historial de reportes en un momento.';
          }
          return;
        }

        const statusRes = await fetch(`/api/schedules/${id}/status`);
        if (!statusRes.ok) return;

        const job = await statusRes.json();
        if (job.status === 'running') {
          if (statusEl) {
            statusEl.style.color = 'var(--text-muted)';
            statusEl.textContent = job.step || 'Generando con Claude Sonnet…';
          }
        } else if (job.status === 'completed') {
          clearInterval(pollInterval);
          if (btn) btn.disabled = false;
          if (job.whatsapp_error) {
            if (statusEl) {
              statusEl.style.color = 'var(--c-yellow)';
              statusEl.textContent = `Newsletter generado pero aviso de WhatsApp: ${job.whatsapp_error}`;
            }
          } else {
            if (statusEl) {
              statusEl.style.color = 'var(--c-green)';
              statusEl.textContent = `✓ Enviado por WhatsApp exitosamente. Reporte guardado en historial.`;
            }
          }
          await loadSchedules();
        } else if (job.status === 'failed') {
          clearInterval(pollInterval);
          if (btn) btn.disabled = false;
          if (statusEl) {
            statusEl.style.color = 'var(--c-red)';
            statusEl.textContent = `Error: ${job.error || 'Fallo en la ejecución'}`;
          }
        }
      } catch (err) {
        console.error('Error sondeando schedule status:', err);
      }
    }, 2000);

  } catch (e) {
    if (btn) btn.disabled = false;
    if (statusEl) {
      statusEl.style.color = 'var(--c-red)';
      statusEl.textContent = `Error: ${e.message}`;
    }
  }
}

/** Activa/desactiva un schedule */
async function toggleScheduleItem(id) {
  try {
    const r = await fetch(`/api/schedules/${id}/toggle`, { method: 'PATCH' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    await loadSchedules();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

/** Elimina un schedule con confirmación */
async function deleteScheduleItem(id) {
  if (!confirm('¿Eliminar esta programación?')) return;
  try {
    const r = await fetch(`/api/schedules/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    await loadSchedules();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

/** Convierte una expresión cron a texto legible */
function _humanizeCron(cron) {
  const map = {
    '0 7 * * 1': 'Lunes 7:00 am',
    '0 7 * * 5': 'Viernes 7:00 am',
    '0 6 * * 5': 'Viernes 6:00 am',
    '0 7 1 * *': 'Día 1 del mes',
    '0 7 * * 1,3,5': 'L-M-V 7:00 am',
    '*/15 * * * *': 'Cada 15 min',
  };
  return map[cron] || cron;
}

// ══════════════════════════════════════════════════════
// HISTORIAL DE REPORTES
// ══════════════════════════════════════════════════════
let _currentReportId = null;   // ID del reporte activo (newsletter tab)
let _histActiveId = null;   // ID seleccionado en el panel Historial

/** Carga la lista de reportes desde /api/reports */
async function loadHistorial() {
  const list = document.getElementById('histList');
  if (!list) return;
  list.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem;padding:.5rem 0;">Cargando…</p>';
  try {
    const r = await fetch('/api/reports');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { reports } = await r.json();
    renderHistorialList(reports);
  } catch (e) {
    list.innerHTML = `<p style="color:var(--c-red);font-size:.82rem;">${esc(e.message)}</p>`;
  }
}

/** Renderiza la lista de ítems en el panel izquierdo del Historial */
function renderHistorialList(reports) {
  const list = document.getElementById('histList');
  if (!list) return;
  if (!reports || !reports.length) {
    list.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem;padding:.5rem 0;">Aún no hay reportes generados.</p>';
    return;
  }
  list.innerHTML = reports.map(r => {
    const ejes = (r.config && r.config.ejes) ? r.config.ejes.slice(0, 2).join(', ') : '';
    const isActive = r.id === _histActiveId;
    return `<div id="hist-item-${r.id}"
      onclick="loadHistorialReport('${r.id}')"
      style="padding:.65rem .75rem; border-radius:8px; cursor:pointer; margin-bottom:.4rem;
             border:1px solid ${isActive ? 'var(--c-blue-light)' : 'var(--border-color)'};
             background:${isActive ? 'var(--c-blue-tint)' : '#fff'};
             transition:all .12s;">
      <div style="font-weight:600;font-size:.82rem;color:var(--c-blue-dark);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        ${esc(r.titulo || 'Sin título')}
      </div>
      <div style="font-size:.72rem;color:var(--text-muted);margin-top:.2rem;">
        ${_fmtDate(r.created_at)} · <span style="text-transform:capitalize">${esc(r.origen)}</span>
      </div>
      ${ejes ? `<div style="font-size:.71rem;color:var(--text-muted);margin-top:.15rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(ejes)}</div>` : ''}
    </div>`;
  }).join('');
}

/** Carga el detalle de un reporte y lo renderiza en la vista derecha */
async function loadHistorialReport(id) {
  _histActiveId = id;
  // Resaltar ítem activo en la lista
  document.querySelectorAll('[id^="hist-item-"]').forEach(el => {
    const isThis = el.id === `hist-item-${id}`;
    el.style.background = isThis ? 'var(--c-blue-tint)' : '#fff';
    el.style.borderColor = isThis ? 'var(--c-blue-light)' : 'var(--border-color)';
  });

  const out = document.getElementById('histOutput');
  out.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;min-height:200px;gap:.75rem;color:var(--text-muted);font-size:.88rem;">
    <span class="spinner"></span> Cargando reporte…</div>`;

  try {
    const r = await fetch(`/api/reports/${id}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const report = await r.json();

    // Reutilizar renderNewsletter pero apuntando a histOutput
    const tmp = document.createElement('div');
    const savedOut = document.getElementById('output');

    // Renderizar en el panel de historial
    out.innerHTML = '';
    const toolbar = document.createElement('div');
    toolbar.className = 'toolbar';
    toolbar.innerHTML = `
      <span style="font-size:.8rem;color:var(--text-muted);">${_fmtDate(report.created_at)} · ${esc(report.origen)}</span>
      <div style="display:flex;gap:.5rem;">
        <button class="btn-ghost" onclick="downloadPDF('histOutput', this)" style="font-size:.82rem;">Descargar PDF</button>
        <button class="btn-ghost" onclick="deleteReport('${id}')" style="font-size:.82rem;border-color:var(--c-red);color:var(--c-red);">Eliminar</button>
      </div>`;
    out.appendChild(toolbar);

    const nlDiv = document.createElement('div');
    nlDiv.id = '__hist_nl_tmp';
    out.appendChild(nlDiv);

    // Trick: renderNewsletter escribe en #output; redirect temporalmente
    const origOut = document.getElementById('output');
    origOut.__histRedirect = true;
    // Build newsletter HTML manually to avoid hijacking #output
    const d = report.newsletter;
    let cifrasHtml = '';
    if (d.cifras && d.cifras.length) {
      const cards = d.cifras.map(c => {
        const u = formatUrl(c.url);
        return `
        <div class="cifra-card">
          <div class="cifra-dato">${esc(c.dato)}</div>
          <div class="cifra-ctx">${esc(c.contexto || '')}</div>
          ${u
            ? `<div class="cifra-src"><a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-dark);font-weight:600;text-decoration:underline;">${esc(c.fuente || 'Ver fuente')} ↗</a>${c.fecha_publicacion ? ` · <span style="font-weight:500;opacity:0.85;">${esc(c.fecha_publicacion)}</span>` : ''}</div>`
            : c.fuente ? `<div class="cifra-src">${esc(c.fuente)}${c.fecha_publicacion ? ` · <span style="font-weight:500;opacity:0.85;">${esc(c.fecha_publicacion)}</span>` : ''}</div>` : ''}
        </div>`;
      }).join('');
      cifrasHtml = `<div class="nl-cifras"><p class="nl-cifras-title">Cifras importantes del sector</p><div class="cifras-grid">${cards}</div></div>`;
    }
    const itemsHtml = (d.items || []).map(it => {
      const u = formatUrl(it.url);
      const titleHtml = u
        ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-dark);text-decoration:none;">${esc(it.titular || '')}</a>`
        : esc(it.titular || '');
      const srcHtml = u
        ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-light);font-weight:600;text-decoration:underline;">${esc(it.fuente || 'Ver enlace')} ↗</a>`
        : esc(it.fuente || '—');

      return `
      <div class="nl-item">
        ${it.eje ? `<div class="nl-eje">${esc(it.eje)}</div>` : ''}
        <h3>${titleHtml}</h3>
        <p>${esc(it.resumen || '')}</p>
        ${it.por_que_importa ? `<div class="nl-why"><b>Por qué importa:</b> ${esc(it.por_que_importa)}</div>` : ''}
        <p class="nl-src">Fuente: ${srcHtml}${it.fecha_publicacion ? ` · <span style="color:var(--text-muted);font-weight:500;">📅 ${esc(it.fecha_publicacion)}</span>` : ''}</p>
      </div>`;
    }).join('');
    const oppsHtml = (d.oportunidades && d.oportunidades.length) ? `
      <div class="nl-opps">
        <h4>Oportunidades accionables</h4>
        <ul>${d.oportunidades.map(o => {
      if (typeof o === 'string') return `<li>${esc(o)}</li>`;
      const u = formatUrl(o.url);
      const src = u
        ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" style="color:var(--c-blue-light);font-weight:600;text-decoration:underline;">${esc(o.fuente || 'Ver convocatoria')} ↗</a>`
        : o.fuente ? esc(o.fuente) : '';
      return `<li>${esc(o.texto || o.text || '')}${src ? ` <span class="nl-opp-src">— ${src}</span>` : ''}</li>`;
    }).join('')}</ul>
      </div>` : '';

    nlDiv.innerHTML = `
      <div class="nl-head">
        <div class="nl-kicker">Universidad de La Sabana</div>
        <div class="nl-title">${esc(d.titulo || 'Newsletter Ejecutivo')}</div>
        <div class="nl-meta">${esc(d.fecha || '')}${d.contexto ? ' - ' + esc(d.contexto) : ''}</div>
      </div>
      ${cifrasHtml}${itemsHtml}${oppsHtml}`;

  } catch (e) {
    out.innerHTML = `<div style="padding:2rem;color:var(--c-red);">Error: ${esc(e.message)}</div>`;
  }
}

/** Elimina un reporte y recarga la lista */
async function deleteReport(id) {
  if (!confirm('¿Eliminar este reporte del historial? Esta acción no se puede deshacer.')) return;
  try {
    const r = await fetch(`/api/reports/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    _histActiveId = null;
    document.getElementById('histOutput').innerHTML = `
      <div class="empty" id="histEmpty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="10"/>
        </svg>
        <div>Selecciona un reporte de la lista para verlo.</div>
      </div>`;
    await loadHistorial();
  } catch (e) {
    alert(`Error al eliminar: ${e.message}`);
  }
}

/** Exporta el newsletter a PDF usando el motor de impresión nativo del navegador */
function downloadPDF(containerId, btnEl) {
  const el = document.getElementById(containerId);
  if (!el) {
    alert('No hay ningún newsletter seleccionado para exportar.');
    return;
  }

  const titleEl = el.querySelector('.nl-title');
  const title = titleEl ? titleEl.textContent.trim() : 'Newsletter Ejecutivo GovLab';
  const cleanTitle = title.replace(/[^a-z0-9áéíóúÁÉÍÓÚñÑ\s]/gi, '').trim() || 'Newsletter_Ejecutivo';
  const originalTitle = document.title;

  document.title = `${cleanTitle} - ${new Date().toISOString().slice(0, 10)}`;

  window.print();

  setTimeout(() => {
    document.title = originalTitle;
  }, 1000);
}

/** Formatea una fecha ISO a string legible en español */
function _fmtDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('es-CO', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch { return iso; }
}

// ══════════════════════════════════════════════════════
async function checkServerKeyStatus() {
  const serverStatusEl = document.getElementById('serverKeyStatus');
  if (!serverStatusEl) return;
  try {
    const response = await fetch('/api/config/status');
    if (response.ok) {
      const data = await response.json();
      if (data.has_api_key) {
        serverStatusEl.textContent = 'Configurada en el servidor (ANTHROPIC_API_KEY) ✓';
        serverStatusEl.style.color = 'var(--c-green)';
      } else {
        serverStatusEl.textContent = 'Sin configurar en el servidor (Falta ANTHROPIC_API_KEY)';
        serverStatusEl.style.color = 'var(--c-red)';
      }
    } else {
      serverStatusEl.textContent = 'Error al verificar';
      serverStatusEl.style.color = 'var(--c-yellow)';
    }
  } catch (e) {
    serverStatusEl.textContent = 'Error de conexión con el backend';
    serverStatusEl.style.color = 'var(--c-yellow)';
  }
}

function updateBrowserKeyStatusLabel() {
  // Función legacy conservada para compatibilidad
}

async function checkWhatsAppStatus() {
  const srvEl = document.getElementById('openwaServerStatus');
  const sesEl = document.getElementById('openwaSessionStatus');
  const helpEl = document.getElementById('openwaHelpText');
  if (!srvEl || !sesEl) return;

  try {
    const r = await fetch('/api/whatsapp/status');
    const data = await r.json();

    if (data.online) {
      srvEl.textContent = `En línea (${data.url})`;
      srvEl.style.color = 'var(--c-green)';

      if (data.connected) {
        sesEl.textContent = 'Conectado a WhatsApp ✓';
        sesEl.style.color = 'var(--c-green)';
        if (helpEl) helpEl.textContent = 'Listo para enviar newsletters por WhatsApp.';
      } else {
        sesEl.textContent = 'Pendiente de escanear QR';
        sesEl.style.color = 'var(--c-yellow)';
        if (helpEl) helpEl.textContent = 'El servidor de WhatsApp está corriendo pero requiere vincular tu WhatsApp escaneando el código QR en la consola de WhatsApp.';
      }
    } else {
      srvEl.textContent = `Desconectado (${data.url})`;
      srvEl.style.color = 'var(--c-red)';
      sesEl.textContent = 'No disponible';
      sesEl.style.color = 'var(--text-muted)';
      if (helpEl) helpEl.textContent = 'Para activar el envío por WhatsApp, verifica la configuración de EVOLUTION_API_URL o OPENWA_API_URL en tu servidor.';
    }
  } catch (e) {
    srvEl.textContent = 'Error al consultar';
    srvEl.style.color = 'var(--c-yellow)';
    sesEl.textContent = '—';
  }
}

function loadConfigTab() {
  const modelGen = localStorage.getItem('claude_model_generation') || 'claude-sonnet-4-6';
  const modelAssist = localStorage.getItem('claude_model_assist') || 'claude-haiku-4-5-20251001';

  const genSelect = document.getElementById('modelGenSelect');
  const assistSelect = document.getElementById('modelAssistSelect');

  if (genSelect) genSelect.value = modelGen;
  if (assistSelect) assistSelect.value = modelAssist;

  checkServerKeyStatus();
  checkWhatsAppStatus();
}

function saveConfig() {
  const genSelect = document.getElementById('modelGenSelect');
  const assistSelect = document.getElementById('modelAssistSelect');

  if (genSelect) {
    localStorage.setItem('claude_model_generation', genSelect.value);
  }
  if (assistSelect) {
    localStorage.setItem('claude_model_assist', assistSelect.value);
  }

  const badge = document.getElementById('configSavedBadge');
  if (badge) {
    badge.textContent = 'Configuración Guardada';
    badge.classList.add('show');
    setTimeout(() => badge.classList.remove('show'), 3000);
  }
}

function clearConfig() {
  localStorage.removeItem('claude_model_generation');
  localStorage.removeItem('claude_model_assist');
  localStorage.removeItem('openai_model_generation');
  localStorage.removeItem('openai_model_assist');

  const genSelect = document.getElementById('modelGenSelect');
  const assistSelect = document.getElementById('modelAssistSelect');
  if (genSelect) genSelect.value = 'claude-sonnet-4-6';
  if (assistSelect) assistSelect.value = 'claude-haiku-4-5-20251001';

  const badge = document.getElementById('configSavedBadge');
  if (badge) {
    badge.textContent = 'Configuración Restablecida';
    badge.classList.add('show');
    setTimeout(() => badge.classList.remove('show'), 3000);
  }
}

function toggleApiKeyVisibility() {
  const input = document.getElementById('apiKeyInput');
  const btn = document.getElementById('toggleVisibilityBtn');
  if (!input || !btn) return;
  if (input.type === 'password') {
    input.type = 'text';
    btn.textContent = 'Ocultar';
  } else {
    input.type = 'password';
    btn.textContent = 'Mostrar';
  }
}

// ══════════════════════════════════════════════════════
// UTILS
// ══════════════════════════════════════════════════════
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Limpieza de claves obsoletas de localStorage
try {
  localStorage.removeItem('anthropic_api_key');
  localStorage.removeItem('anthropic_model_assist');
  localStorage.removeItem('anthropic_model_generation');
  localStorage.removeItem('openai_api_key');
} catch (e) {}

// Carga inicial de estado de llaves
checkServerKeyStatus();

// ══════════════════════════════════════════════════════
// TUTORIAL DE GUÍA RÁPIDA (PARA DIRECTIVOS)
// ══════════════════════════════════════════════════════
const tutorialSteps = [
  {
    badge: "Bienvenido",
    title: "Guía Rápida: Newsletter Ejecutivo",
    desc: "Esta herramienta automatiza la generación de boletines altamente ejecutivos y personalizados para la comunidad directiva de la Universidad de La Sabana, integrando búsquedas inteligentes e información institucional.",
    visual: `<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><line x1="10" y1="9" x2="8" y2="9"></line></svg>`,
    tab: "nl"
  },
  {
    badge: "Paso 1 de 5",
    title: "Configuración de la Edición",
    desc: "En la sección <b>Newsletter</b>, personaliza el tipo de boletín, selecciona los ejes temáticos relevantes y define las notas del destinatario. Al presionar <i>Generar newsletter</i>, el agente iniciará una búsqueda y análisis en tiempo real.",
    visual: `<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"></line><line x1="4" y1="10" x2="4" y2="3"></line><line x1="12" y1="21" x2="12" y2="12"></line><line x1="12" y1="8" x2="12" y2="3"></line><line x1="20" y1="21" x2="20" y2="16"></line><line x1="20" y1="12" x2="20" y2="3"></line><line x1="1" y1="14" x2="7" y2="14"></line><line x1="9" y1="8" x2="15" y2="8"></line><line x1="17" y1="16" x2="23" y2="16"></line></svg>`,
    tab: "nl"
  },
  {
    badge: "Paso 2 de 5",
    title: "Base de Conocimiento / Contexto",
    desc: "En el <b>Editor de Contexto</b>, administras los documentos de base de conocimiento (e.g., agendas estratégicas, perfiles). El agente los consulta dinámicamente para alinear el tono institucional de cada noticia.",
    visual: `<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><path d="M12 11v6"></path><path d="M9 14h6"></path></svg>`,
    tab: "ctx"
  },
  {
    badge: "Paso 3 de 5",
    title: "Automatización de Envíos",
    desc: "En la pestaña de <b>Envío</b> puedes programar de forma recurrentes las entregas a través de reglas cron (por ejemplo, cada lunes a las 7:00 AM) y enviarlas automáticamente por correo electrónico.",
    visual: `<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline><path d="M22 2L11 13"></path><path d="M22 2l-7 20-4-9-9-4 20-7z"></path></svg>`,
    tab: "send"
  },
  {
    badge: "Paso 4 de 5",
    title: "Historial de Reportes",
    desc: "En <b>Historial</b>, accede a todos los boletines generados anteriormente. Esto te permite auditar las búsquedas exactas realizadas por el agente inteligente y reimprimir o descargar las versiones en PDF en cualquier momento.",
    visual: `<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line><path d="M8 11h6"></path><path d="M11 8v6"></path></svg>`,
    tab: "hist"
  },
  {
    badge: "Paso 5 de 5",
    title: "Configuración y Conexiones",
    desc: "Por último, en <b>Configuración</b> puedes gestionar la conexión con los servicios de inteligencia artificial, la base de datos de contexto y el servicio de envío de correos.",
    visual: `<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>`,
    tab: "config"
  }
];

let currentTutorialStep = 0;

function startTutorial() {
  currentTutorialStep = 0;
  renderTutorialStep();
  const el = document.getElementById('tutorialOverlay');
  if (el) {
    el.style.display = 'flex';
    el.classList.add('show');
  }
}

function closeTutorial() {
  const el = document.getElementById('tutorialOverlay');
  if (el) {
    el.classList.remove('show');
    el.style.display = 'none';
  }
  localStorage.setItem('govlab_tutorial_seen', 'true');
}

function nextTutorialStep() {
  if (currentTutorialStep < tutorialSteps.length - 1) {
    currentTutorialStep++;
    renderTutorialStep();
  } else {
    closeTutorial();
  }
}

function renderTutorialStep() {
  const step = tutorialSteps[currentTutorialStep];
  document.getElementById('tBadge').textContent = step.badge;
  document.getElementById('tTitle').textContent = step.title;
  document.getElementById('tDesc').innerHTML = step.desc;
  document.getElementById('tVisual').innerHTML = step.visual;

  if (step.tab) {
    switchTab(step.tab);
  }

  const nextBtn = document.getElementById('tBtnNext');
  if (currentTutorialStep === tutorialSteps.length - 1) {
    nextBtn.textContent = "Finalizar";
  } else {
    nextBtn.textContent = "Siguiente";
  }

  const dotsContainer = document.getElementById('tDots');
  dotsContainer.innerHTML = '';
  tutorialSteps.forEach((_, idx) => {
    const dot = document.createElement('div');
    dot.className = `tutorial-step-dot${idx === currentTutorialStep ? ' active' : ''}`;
    dot.style.cursor = 'pointer';
    dot.onclick = () => {
      currentTutorialStep = idx;
      renderTutorialStep();
    };
    dotsContainer.appendChild(dot);
  });
}

// Auto-arranque tras carga de página
window.addEventListener('DOMContentLoaded', () => {
  if (localStorage.getItem('govlab_tutorial_seen') !== 'true') {
    setTimeout(() => {
      startTutorial();
    }, 1200);
  }
});
