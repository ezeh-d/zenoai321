// Live Project Activity View -- a small Event Bus projection of observable
// project work. It intentionally shows actions/evidence, never model chain
// of thought, fabricated progress, or a polling animation loop.

let stylesReady = false;

function ensureStyles() {
  if (stylesReady) return;
  stylesReady = true;
  const style = document.createElement('style');
  style.textContent = `
    .zpa-overlay { display:none; position:fixed; inset:0; z-index:10020; background:rgba(2,5,12,.7); align-items:center; justify-content:center; padding:4vh 3vw; }
    .zpa-overlay.open { display:flex; }
    .zpa-card { width:min(1040px,94vw); height:min(760px,90vh); display:flex; flex-direction:column; overflow:hidden; border:1px solid rgba(105,175,255,.35); border-radius:15px; background:#090d17; box-shadow:0 24px 90px rgba(0,0,0,.62); color:#dce8ff; font-family:system-ui,sans-serif; }
    .zpa-head { display:flex; align-items:center; gap:10px; padding:12px 15px; border-bottom:1px solid rgba(130,180,255,.16); }
    .zpa-title { flex:1; font-weight:750; letter-spacing:.02em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .zpa-state { border:1px solid rgba(110,210,165,.42); border-radius:999px; color:#8fe6b2; font:700 10px system-ui,sans-serif; letter-spacing:.08em; padding:4px 8px; }
    .zpa-close { border:0; background:transparent; color:#aabbd8; font-size:24px; cursor:pointer; }
    .zpa-body { min-height:0; flex:1; display:grid; grid-template-columns:minmax(270px,.78fr) minmax(340px,1.22fr); }
    .zpa-side { overflow:auto; padding:14px; border-right:1px solid rgba(130,180,255,.13); }
    .zpa-main { min-width:0; overflow:auto; padding:14px; }
    .zpa-label { margin:10px 0 4px; color:#89a0c7; font:700 10px system-ui,sans-serif; letter-spacing:.09em; text-transform:uppercase; }
    .zpa-value { font-size:13px; overflow-wrap:anywhere; }
    .zpa-step { display:flex; gap:7px; padding:6px 2px; font-size:12px; border-bottom:1px solid rgba(130,180,255,.07); }
    .zpa-step b { width:13px; color:#8fe6b2; } .zpa-step.working b,.zpa-step.waiting b { color:#f5c518; } .zpa-step.failed b { color:#fb7185; }
    .zpa-file { font:11.5px/1.55 ui-monospace,'Cascadia Code',monospace; color:#a9c9ff; overflow-wrap:anywhere; }
    .zpa-warning { color:#f5c518; font-size:12px; } .zpa-error { color:#ff9da9; font-size:12px; }
    .zpa-preview { min-height:190px; background:#050810; border:1px solid rgba(130,180,255,.14); border-radius:8px; overflow:auto; }
    .zpa-preview pre { margin:0; padding:12px; white-space:pre-wrap; overflow-wrap:anywhere; color:#d3e0f7; font:11.5px/1.5 ui-monospace,'Cascadia Code',monospace; }
    .zpa-preview iframe { width:100%; min-height:280px; border:0; background:#fff; }
    .zpa-choice-row { display:flex; flex-wrap:wrap; gap:7px; margin-top:8px; }
    .zpa-choice { border:1px solid rgba(120,180,255,.34); border-radius:7px; background:rgba(85,135,220,.13); color:#dce8ff; padding:7px 9px; cursor:pointer; font-size:12px; }
    .zpa-choice:hover { background:rgba(85,135,220,.27); }
    .zpa-path { display:flex; gap:6px; margin-top:8px; } .zpa-path input { min-width:0; flex:1; background:#101827; color:#dce8ff; border:1px solid rgba(120,180,255,.32); border-radius:6px; padding:7px; }
    .zpa-muted { color:#8fa0bb; font-size:12px; }
    @media (max-width:720px) { .zpa-body { grid-template-columns:1fr; } .zpa-side { border-right:0; border-bottom:1px solid rgba(130,180,255,.13); max-height:42%; } }
  `;
  document.head.appendChild(style);
}

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function markFor(state) {
  return state === 'completed' ? '✓' : state === 'failed' ? '!' : state === 'working' ? '●' : '○';
}

export function createLiveActivityView() {
  ensureStyles();
  const projects = new Map();
  let activeId = '';
  const overlay = el('div', 'zpa-overlay');
  const card = el('section', 'zpa-card');
  const head = el('div', 'zpa-head');
  const title = el('div', 'zpa-title', 'Live Activity');
  const state = el('span', 'zpa-state', 'WAITING');
  const close = el('button', 'zpa-close', '×'); close.type = 'button'; close.title = 'Close activity view';
  const body = el('div', 'zpa-body'); const side = el('div', 'zpa-side'); const main = el('div', 'zpa-main');
  head.append(title, state, close); body.append(side, main); card.append(head, body); overlay.appendChild(card); document.body.appendChild(overlay);
  close.addEventListener('click', () => overlay.classList.remove('open'));

  function current() { return projects.get(activeId) || [...projects.values()].at(-1) || null; }
  function show() { overlay.classList.add('open'); render(); }

  async function selectDestination(project, destination) {
    try {
      const response = await fetch('/api/projects/destination', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:project.name, destination}) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Could not save the destination.');
      projects.set(result.project.id, result.project); activeId = result.project.id; render();
      // This is an explicit owner click, not an autonomous retry.  The
      // dashboard's normal conversation path receives it and continues the
      // already-requested project with the confirmed full path.
      window.dispatchEvent(new CustomEvent('zeno-project-destination-selected', { detail: result.project }));
    } catch (error) {
      const note = el('div', 'zpa-error', String(error.message || error)); side.appendChild(note);
    }
  }

  function destinationChooser(project) {
    const box = el('div');
    box.append(el('div', 'zpa-label', 'Save location needed'), el('div', 'zpa-muted', 'Divine, where should ZENO save this new project? No files have been created.'));
    const choices = el('div', 'zpa-choice-row');
    for (const choice of ['Desktop', 'Documents', 'ZENO Projects']) {
      const button = el('button', 'zpa-choice', choice); button.type = 'button';
      button.addEventListener('click', () => selectDestination(project, choice)); choices.appendChild(button);
    }
    const path = el('div', 'zpa-path'); const input = document.createElement('input'); input.placeholder = 'Another full folder path';
    const choose = el('button', 'zpa-choice', 'Use folder'); choose.type = 'button'; choose.addEventListener('click', () => selectDestination(project, input.value));
    path.append(input, choose); box.append(choices, path); return box;
  }

  function appendList(container, label, values, className = '') {
    if (!values || !values.length) return;
    container.appendChild(el('div', 'zpa-label', label));
    for (const value of values) container.appendChild(el('div', className || 'zpa-value', typeof value === 'string' ? value : String(value)));
  }

  function render() {
    const project = current();
    side.replaceChildren(); main.replaceChildren();
    if (!project) { title.textContent = 'Live Activity'; state.textContent = 'WAITING'; side.appendChild(el('div', 'zpa-muted', 'No project is active.')); return; }
    title.textContent = project.name || 'Untitled project'; state.textContent = project.state || 'WAITING';
    side.append(el('div', 'zpa-label', 'Current task'), el('div', 'zpa-value', project.state || 'WAITING'));
    side.append(el('div', 'zpa-label', 'Active agent'), el('div', 'zpa-value', project.active_agent || 'ZENO'));
    side.append(el('div', 'zpa-label', 'Progress'));
    const progress = typeof project.progress_percent === 'number' ? `${project.progress_percent}% (planned steps)` : `${project.completed_steps || 0} completed step${project.completed_steps === 1 ? '' : 's'} (no estimated percentage)`;
    side.appendChild(el('div', 'zpa-value', progress));
    side.append(el('div', 'zpa-label', 'Save path'), el('div', 'zpa-value', project.project_path || project.destination || 'Awaiting your choice'));
    if (project.state === 'WAITING' && !project.destination) side.appendChild(destinationChooser(project));
    appendList(side, 'Tools used', project.tools);
    appendList(side, 'Files changed', project.files, 'zpa-file');
    appendList(side, 'Warnings', project.warnings, 'zpa-warning'); appendList(side, 'Errors', project.errors, 'zpa-error');

    main.appendChild(el('div', 'zpa-label', 'Completed and current steps'));
    const steps = Array.isArray(project.steps) ? project.steps : [];
    if (!steps.length) main.appendChild(el('div', 'zpa-muted', 'Waiting for an observable project action.'));
    for (const step of steps.slice(-30)) {
      const row = el('div', `zpa-step ${step.state || ''}`); row.append(el('b', '', markFor(step.state)), el('span', '', step.label || 'Project step'));
      main.appendChild(row); if (step.detail) main.appendChild(el('div', 'zpa-muted', step.detail));
    }
    if (project.preview && project.preview.content) {
      main.appendChild(el('div', 'zpa-label', `Preview: ${project.preview.file || 'current file'}`));
      const preview = el('div', 'zpa-preview');
      if (/\.html?$/i.test(project.preview.file || '')) {
        const frame = document.createElement('iframe'); frame.sandbox = ''; frame.srcdoc = project.preview.content; preview.appendChild(frame);
      } else preview.appendChild(el('pre', '', project.preview.content));
      main.appendChild(preview);
    }
  }

  function consumeEvent(update) {
    const type = String(update?.type || ''); const payload = update?.payload || {};
    if (type === 'project.activity' && payload.project) {
      projects.set(payload.project.id, payload.project); activeId = payload.project.id; show(); return true;
    }
    if (type === 'ui.workspace_code' && payload.project) {
      const project = [...projects.values()].find(item => item.name === payload.project);
      if (project) { project.preview = { file: payload.file || '', content: payload.content || '' }; project.files = payload.files || project.files; render(); }
      return !!project;
    }
    return false;
  }

  async function refresh() {
    try {
      const data = await (await fetch('/api/projects/activity')).json();
      for (const project of data.projects || []) projects.set(project.id, project);
      const pending = [...projects.values()].find(project => !['COMPLETED', 'FAILED'].includes(project.state));
      if (pending) { activeId = pending.id; show(); } else render();
    } catch (_) { /* The activity panel remains dormant if the local API is unavailable. */ }
  }

  function dispose() { overlay.remove(); projects.clear(); }
  return { consumeEvent, refresh, open: show, close: () => overlay.classList.remove('open'), dispose };
}
