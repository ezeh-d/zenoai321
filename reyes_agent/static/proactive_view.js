// Proactive panel -- a lightweight projection of persisted heartbeat state.
// It owns no scheduler, timer or notification channel; refresh is explicit.

let stylesReady = false;

function ensureStyles() {
  if (stylesReady) return;
  stylesReady = true;
  const style = document.createElement('style');
  style.textContent = `
    .zeno-proactive-overlay { display:none; position:fixed; inset:0; z-index:10022; background:rgba(2,5,12,.72); align-items:center; justify-content:center; padding:4vh 3vw; }
    .zeno-proactive-overlay.open { display:flex; }
    .zeno-proactive-card { width:min(720px,94vw); max-height:88vh; overflow:auto; border:1px solid rgba(125,178,255,.38); border-radius:14px; background:#090d17; color:#dce8ff; padding:16px; font-family:system-ui,sans-serif; }
    .zeno-proactive-head { display:flex; align-items:center; gap:9px; } .zeno-proactive-head h2 { margin:0; flex:1; font-size:18px; }
    .zeno-proactive-head button, .zeno-proactive-row button { border:1px solid rgba(120,180,255,.34); border-radius:7px; background:rgba(85,135,220,.13); color:#dce8ff; padding:6px 9px; cursor:pointer; }
    .zeno-proactive-summary { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0; } .zeno-proactive-pill { border:1px solid rgba(110,210,165,.36); border-radius:999px; padding:4px 8px; font-size:12px; }
    .zeno-proactive-row { border-top:1px solid rgba(130,180,255,.14); padding:10px 0; } .zeno-proactive-row strong { display:block; } .zeno-proactive-row p { margin:4px 0 8px; color:#b8c8e7; white-space:pre-wrap; overflow-wrap:anywhere; }
    .zeno-proactive-muted { color:#8fa0bb; font-size:13px; }
  `;
  document.head.appendChild(style);
}

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

async function json(url, options) {
  const response = await fetch(url, options);
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.detail || 'Unavailable');
  return value;
}

export function createProactiveView() {
  ensureStyles();
  const overlay = el('div', 'zeno-proactive-overlay');
  const card = el('section', 'zeno-proactive-card');
  const head = el('header', 'zeno-proactive-head');
  const title = el('h2', '', 'ZENO Proactive');
  const refresh = el('button', '', 'Refresh'); refresh.type = 'button';
  const close = el('button', '', '×'); close.type = 'button'; close.title = 'Close proactive panel';
  const summary = el('div', 'zeno-proactive-summary');
  const body = el('div');
  head.append(title, refresh, close); card.append(head, summary, body); overlay.append(card); document.body.appendChild(overlay);

  async function render() {
    summary.replaceChildren(); body.replaceChildren();
    try {
      const [status, notices] = await Promise.all([json('/api/proactive/status'), json('/api/notices')]);
      const engine = status.engine || {}; const inbox = status.inbox || {};
      summary.append(el('span', 'zeno-proactive-pill', status.enabled ? 'Enabled' : 'Paused'),
                     el('span', 'zeno-proactive-pill', `${engine.registered_checks || 0} checks`),
                     el('span', 'zeno-proactive-pill', `${inbox.held || 0} held`),
                     el('span', 'zeno-proactive-pill', `${inbox.surfaced || 0} surfaced`));
      if (!notices.length) {
        body.append(el('p', 'zeno-proactive-muted', 'No proactive updates waiting.'));
        return;
      }
      for (const notice of notices) {
        const row = el('article', 'zeno-proactive-row');
        const dismiss = el('button', '', 'Dismiss'); dismiss.type = 'button';
        dismiss.addEventListener('click', async () => {
          await json(`/api/notices/${encodeURIComponent(notice.id)}/dismiss`, { method: 'POST' });
          await render();
        });
        row.append(el('strong', '', notice.title || 'ZENO update'),
                   el('p', '', notice.summary || ''), dismiss);
        body.append(row);
      }
    } catch (error) {
      body.append(el('p', 'zeno-proactive-muted', `Proactive state unavailable: ${String(error.message || error)}`));
    }
  }

  refresh.addEventListener('click', () => void render());
  close.addEventListener('click', () => overlay.classList.remove('open'));
  return { open() { overlay.classList.add('open'); void render(); }, close() { overlay.classList.remove('open'); } };
}
