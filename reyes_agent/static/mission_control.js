// Lazy, zero-polling projection of /api/control-plane/mission-control.
let root = null;
let style = null;
let state = null;
let active = 'OVERVIEW';

function ensureStyle() {
  if (style) return;
  style = document.createElement('style');
  style.textContent = `
    .zmc{position:fixed;inset:24px;z-index:10040;background:#07101df5;border:1px solid #2e5775;border-radius:18px;color:#dcecff;display:grid;grid-template-columns:220px 1fr;overflow:hidden;box-shadow:0 24px 90px #000c;font:13px/1.45 system-ui,sans-serif}
    .zmc nav{padding:18px 12px;background:#091827;border-right:1px solid #183349;overflow:auto}.zmc h2{font-size:15px;letter-spacing:.13em;margin:0 8px 16px;color:#6ed8ff}
    .zmc nav button{width:100%;border:0;background:transparent;color:#91a9bd;text-align:left;border-radius:9px;padding:9px 11px;margin:1px 0;cursor:pointer}.zmc nav button[aria-selected=true]{background:#123149;color:white}
    .zmc main{padding:22px;overflow:auto}.zmc header{display:flex;align-items:center;gap:10px;margin-bottom:18px}.zmc header h3{margin:0 auto 0 0;font-size:20px}.zmc .ctl{border:1px solid #31546b;background:#0c2132;color:#dcecff;border-radius:9px;padding:7px 12px;cursor:pointer}
    .zmc .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:10px}.zmc article{background:#0a1826;border:1px solid #17344a;border-radius:12px;padding:13px;min-width:0}.zmc article b{display:block;color:#73d7ff;margin-bottom:5px}.zmc pre{white-space:pre-wrap;word-break:break-word;margin:0;color:#c4d5e2;font:12px/1.5 ui-monospace,Consolas,monospace;max-height:520px;overflow:auto}
    @media(max-width:700px){.zmc{inset:8px;grid-template-columns:104px 1fr}.zmc nav{padding:12px 6px}.zmc nav button{font-size:10px;padding:8px 5px}.zmc main{padding:13px}.zmc h2{font-size:11px;margin-left:4px}}
  `;
  document.head.appendChild(style);
}

function display(value) {
  if (value === null || value === undefined) return 'Unknown / not measured';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function render() {
  if (!root) return;
  const nav = root.querySelector('nav');
  const body = root.querySelector('.grid');
  root.querySelector('h3').textContent = active.replaceAll('_', ' ');
  nav.querySelectorAll('button[data-section]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.section === active)));
  body.replaceChildren();
  const value = state?.[active];
  const entries = value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value) : [[active, value]];
  for (const [key, item] of entries) {
    const card = document.createElement('article');
    const title = document.createElement('b'); title.textContent = key.replaceAll('_', ' ');
    const pre = document.createElement('pre'); pre.textContent = display(item);
    card.append(title, pre); body.append(card);
  }
}

async function refresh() {
  const response = await fetch('/api/control-plane/mission-control', {cache: 'no-store'});
  if (!response.ok) throw new Error(`Mission Control HTTP ${response.status}`);
  state = await response.json(); render();
}

function close() { root?.remove(); root = null; state = null; }

export async function openMissionControl() {
  if (root) { root.focus(); return; }
  ensureStyle();
  root = document.createElement('section'); root.className = 'zmc'; root.tabIndex = -1;
  const nav = document.createElement('nav'); const brand = document.createElement('h2'); brand.textContent = 'ZENO MISSION CONTROL'; nav.appendChild(brand);
  const sections = ['OVERVIEW','DEVICES','CAPABILITIES','TOOLS','EXTENSIONS','AGENTS','TASKS','MODELS','VOICE','MEMORY','PERMISSIONS','OBSERVABILITY','QUALITY','ERRORS','EVENTS','RESOURCES'];
  for (const section of sections) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.section = section; button.textContent = section.replaceAll('_', ' ');
    button.addEventListener('click', () => { active = section; render(); }); nav.appendChild(button);
  }
  const main = document.createElement('main'); const header = document.createElement('header'); const title = document.createElement('h3');
  const reload = document.createElement('button'); reload.className = 'ctl'; reload.textContent = 'Refresh';
  reload.addEventListener('click', () => refresh().catch(error => { state = {ERRORS:{message:error.message}}; active='ERRORS'; render(); }));
  const dismiss = document.createElement('button'); dismiss.className = 'ctl'; dismiss.textContent = 'Close'; dismiss.addEventListener('click', close);
  header.append(title, reload, dismiss); const grid = document.createElement('div'); grid.className = 'grid'; main.append(header, grid); root.append(nav, main); document.body.appendChild(root); root.focus();
  root.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  try { await refresh(); } catch (error) { state = {ERRORS:{message:error.message}}; active='ERRORS'; render(); }
}

export const closeMissionControl = close;
