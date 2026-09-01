// Live Activity View -- an Event Bus projection of observable work.
//
// Two feeds land here and neither one is simulated:
//   * `build.task`      -- the real execution pipeline (task_engine.py):
//                          verified file writes, captured process output,
//                          HTTP responses from the preview server.
//   * `project.activity` -- the older single-file project write path.
//
// Nothing in this file invents progress. There is no polling timer, no
// animated bar that advances on its own, and no step that turns green
// without a matching event from an executor that actually observed it. A
// percentage is shown only when the backend declared a finite plan; without
// one the panel says so and shows a completed-step count instead.

let stylesReady = false;

function ensureStyles() {
  if (stylesReady) return;
  stylesReady = true;
  const style = document.createElement('style');
  style.textContent = `
    .zpa-overlay { display:none; position:fixed; inset:0; z-index:10020; background:rgba(2,5,12,.7); align-items:center; justify-content:center; padding:4vh 3vw; }
    .zpa-overlay.open { display:flex; }
    .zpa-card { width:min(1180px,96vw); height:min(800px,92vh); display:flex; flex-direction:column; overflow:hidden; border:1px solid rgba(105,175,255,.35); border-radius:15px; background:#090d17; box-shadow:0 24px 90px rgba(0,0,0,.62); color:#dce8ff; font-family:system-ui,sans-serif; }
    .zpa-head { display:flex; align-items:center; gap:10px; padding:12px 15px; border-bottom:1px solid rgba(130,180,255,.16); }
    .zpa-title { flex:1; font-weight:750; letter-spacing:.02em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .zpa-state { border:1px solid rgba(110,210,165,.42); border-radius:999px; color:#8fe6b2; font:700 10px system-ui,sans-serif; letter-spacing:.08em; padding:4px 8px; }
    .zpa-state.bad { border-color:rgba(251,113,133,.5); color:#fb7185; }
    .zpa-state.busy { border-color:rgba(245,197,24,.5); color:#f5c518; }
    .zpa-close { border:0; background:transparent; color:#aabbd8; font-size:24px; cursor:pointer; }
    .zpa-body { min-height:0; flex:1; display:grid; grid-template-columns:minmax(280px,.8fr) minmax(360px,1.2fr); }
    .zpa-side { overflow:auto; padding:14px; border-right:1px solid rgba(130,180,255,.13); }
    .zpa-main { min-width:0; overflow:auto; padding:14px; display:flex; flex-direction:column; gap:6px; }
    .zpa-label { margin:10px 0 4px; color:#89a0c7; font:700 10px system-ui,sans-serif; letter-spacing:.09em; text-transform:uppercase; }
    .zpa-value { font-size:13px; overflow-wrap:anywhere; }
    .zpa-step { display:flex; gap:7px; padding:6px 2px; font-size:12px; border-bottom:1px solid rgba(130,180,255,.07); }
    .zpa-step b { width:13px; color:#8fe6b2; } .zpa-step.working b,.zpa-step.running b,.zpa-step.waiting b { color:#f5c518; }
    .zpa-step.failed b { color:#fb7185; } .zpa-step.pending { color:#7f90ad; } .zpa-step.skipped { color:#94a3b8; }
    .zpa-step.running { color:#ffe9a8; font-weight:650; }
    .zpa-file { font:11.5px/1.55 ui-monospace,'Cascadia Code',monospace; color:#a9c9ff; overflow-wrap:anywhere; padding:1px 4px; border-radius:4px; }
    .zpa-file.active { background:rgba(245,197,24,.15); color:#ffe9a8; }
    .zpa-warning { color:#f5c518; font-size:12px; } .zpa-error { color:#ff9da9; font-size:12px; }
    .zpa-preview { min-height:190px; background:#050810; border:1px solid rgba(130,180,255,.14); border-radius:8px; overflow:auto; }
    .zpa-preview pre { margin:0; padding:12px; white-space:pre-wrap; overflow-wrap:anywhere; color:#d3e0f7; font:11.5px/1.5 ui-monospace,'Cascadia Code',monospace; }
    .zpa-preview iframe { width:100%; min-height:300px; border:0; background:#fff; }
    .zpa-term { background:#04070e; border:1px solid rgba(130,180,255,.16); border-radius:8px; padding:10px; max-height:230px; overflow:auto; font:11.5px/1.5 ui-monospace,'Cascadia Code',monospace; color:#bcd3f2; white-space:pre-wrap; overflow-wrap:anywhere; }
    .zpa-term .cmd { color:#8fe6b2; } .zpa-term .bad { color:#ff9da9; }
    .zpa-bar { height:7px; border-radius:999px; background:rgba(130,180,255,.14); overflow:hidden; margin-top:5px; }
    .zpa-bar i { display:block; height:100%; background:linear-gradient(90deg,#4f8cff,#8fe6b2); }
    .zpa-choice-row { display:flex; flex-wrap:wrap; gap:7px; margin-top:8px; }
    .zpa-choice { border:1px solid rgba(120,180,255,.34); border-radius:7px; background:rgba(85,135,220,.13); color:#dce8ff; padding:7px 9px; cursor:pointer; font-size:12px; }
    .zpa-choice:hover { background:rgba(85,135,220,.27); }
    .zpa-choice:disabled { opacity:.4; cursor:not-allowed; }
    .zpa-choice.danger { border-color:rgba(251,113,133,.45); background:rgba(251,113,133,.12); color:#ffc6cd; }
    .zpa-path { display:flex; gap:6px; margin-top:8px; } .zpa-path input { min-width:0; flex:1; background:#101827; color:#dce8ff; border:1px solid rgba(120,180,255,.32); border-radius:6px; padding:7px; }
    .zpa-muted { color:#8fa0bb; font-size:12px; }
    .zpa-check { font-size:12px; padding:3px 0; } .zpa-check b { width:13px; display:inline-block; }
    .zpa-check.ok b { color:#8fe6b2; } .zpa-check.no b { color:#fb7185; } .zpa-check.no { color:#ffc6cd; }
    @media (max-width:720px) { .zpa-body { grid-template-columns:1fr; } .zpa-side { border-right:0; border-bottom:1px solid rgba(130,180,255,.13); max-height:44%; } }
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
  if (state === 'completed') return '✓';
  if (state === 'failed') return '!';
  if (state === 'working' || state === 'running') return '●';
  if (state === 'skipped') return '–';
  return '○';
}

const BUSY_STATES = ['PLANNING', 'RUNNING', 'VERIFYING', 'RETRYING', 'WAITING_FOR_APPROVAL'];
const DONE_STATES = ['COMPLETED', 'FAILED', 'CANCELLED'];

export function createLiveActivityView() {
  ensureStyles();
  const projects = new Map();
  const tasks = new Map();
  const websiteProjects = new Map();
  let activeId = '';
  let activeKind = '';
  let termAtBottom = true;
  const overlay = el('div', 'zpa-overlay');
  const card = el('section', 'zpa-card');
  const head = el('div', 'zpa-head');
  const title = el('div', 'zpa-title', 'Live Activity');
  const state = el('span', 'zpa-state', 'WAITING');
  const close = el('button', 'zpa-close', '×'); close.type = 'button'; close.title = 'Close activity view';
  const body = el('div', 'zpa-body'); const side = el('div', 'zpa-side'); const main = el('div', 'zpa-main');
  head.append(title, state, close); body.append(side, main); card.append(head, body); overlay.appendChild(card); document.body.appendChild(overlay);
  close.addEventListener('click', () => overlay.classList.remove('open'));

  function currentTask() {
    if (activeKind === 'task' && tasks.has(activeId)) return tasks.get(activeId);
    const open = [...tasks.values()].filter(t => !DONE_STATES.includes(t.current_status));
    return open.at(-1) || [...tasks.values()].at(-1) || null;
  }
  function currentProject() {
    if (activeKind === 'project' && projects.has(activeId)) return projects.get(activeId);
    return [...projects.values()].at(-1) || null;
  }
  function currentWebsite() {
    if (activeKind === 'website' && websiteProjects.has(activeId)) return websiteProjects.get(activeId);
    return [...websiteProjects.values()].at(-1) || null;
  }
  function show() { overlay.classList.add('open'); render(); }

  // --- build task rendering ---------------------------------------------

  async function post(url, taskId) {
    const response = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'That did not work.');
    return result;
  }

  function actionRow(task) {
    const row = el('div', 'zpa-choice-row');
    const folder = el('button', 'zpa-choice', 'Open Folder'); folder.type = 'button';
    folder.disabled = !task.output_path;
    const site = el('button', 'zpa-choice', 'Open Website'); site.type = 'button';
    site.disabled = !task.preview_url;
    const cancel = el('button', 'zpa-choice danger', 'Cancel Task'); cancel.type = 'button';
    cancel.disabled = !task.cancellable;
    const note = el('div', 'zpa-muted', '');
    const fail = (error) => { note.className = 'zpa-error'; note.textContent = String(error.message || error); };
    const ok = (result) => { note.className = 'zpa-muted'; note.textContent = result.message || ''; };
    folder.addEventListener('click', () => post('/api/build/open-folder', task.task_id).then(ok).catch(fail));
    site.addEventListener('click', () => post('/api/build/open-preview', task.task_id).then(ok).catch(fail));
    cancel.addEventListener('click', () => post('/api/build/cancel', task.task_id).then(result => {
      if (result.task) { tasks.set(result.task.task_id, result.task); render(); }
    }).catch(fail));
    row.append(folder, site, cancel);
    const box = el('div'); box.append(row, note);
    return box;
  }

  function renderTask(task) {
    title.textContent = task.title || 'Build task';
    state.textContent = task.current_status || 'PLANNING';
    state.className = 'zpa-state' + (DONE_STATES.includes(task.current_status) && task.current_status !== 'COMPLETED'
      ? ' bad' : BUSY_STATES.includes(task.current_status) ? ' busy' : '');

    side.append(el('div', 'zpa-label', 'Current task'), el('div', 'zpa-value', task.title || '—'));
    const step = task.current_step;
    side.append(el('div', 'zpa-label', 'Current step'),
      el('div', 'zpa-value', step ? step.label : (DONE_STATES.includes(task.current_status) ? 'Finished' : 'Waiting for the next action')));

    side.appendChild(el('div', 'zpa-label', 'Progress'));
    if (typeof task.progress_percent === 'number') {
      side.appendChild(el('div', 'zpa-value',
        `${task.progress_percent}% — ${task.completed_steps} of ${task.planned_total} planned steps`));
      const bar = el('div', 'zpa-bar'); const fill = el('i');
      fill.style.width = `${Math.max(0, Math.min(100, task.progress_percent))}%`;
      bar.appendChild(fill); side.appendChild(bar);
    } else {
      side.appendChild(el('div', 'zpa-value',
        `${task.completed_steps || 0} completed step${task.completed_steps === 1 ? '' : 's'} (no estimated percentage)`));
    }

    side.append(el('div', 'zpa-label', 'Saved at'), el('div', 'zpa-value', task.output_path || 'Not created yet'));
    if (task.preview_url) side.append(el('div', 'zpa-label', 'Running at'), el('div', 'zpa-value', task.preview_url));
    side.appendChild(actionRow(task));

    if (task.current_command) {
      side.append(el('div', 'zpa-label', 'Command running'), el('div', 'zpa-file', task.current_command));
    }
    if (task.retrying && task.retrying.length) {
      side.appendChild(el('div', 'zpa-label', 'Retry status'));
      for (const item of task.retrying) {
        side.appendChild(el('div', 'zpa-warning', `${item.label} — attempt ${item.attempts}: ${item.error || 'retrying'}`));
      }
    }

    const pending = task.pending_steps || [];
    if (pending.length) {
      side.appendChild(el('div', 'zpa-label', `Pending (${pending.length})`));
      for (const label of pending.slice(0, 12)) side.appendChild(el('div', 'zpa-muted', label));
    }

    if (task.files && task.files.length) {
      side.appendChild(el('div', 'zpa-label', `Project files (${task.files.length})`));
      for (const name of task.files) {
        const row = el('div', 'zpa-file' + (name === task.current_file ? ' active' : ''), name);
        side.appendChild(row);
      }
    }
    appendList(side, 'Warnings', task.warnings, 'zpa-warning');
    appendList(side, 'Errors', task.errors, 'zpa-error');
    if (task.error_details) side.append(el('div', 'zpa-label', 'Blocker'), el('div', 'zpa-error', task.error_details));

    // --- main column: steps, real terminal output, real preview
    main.appendChild(el('div', 'zpa-label', 'Steps'));
    const steps = Array.isArray(task.steps) ? task.steps : [];
    if (!steps.length) main.appendChild(el('div', 'zpa-muted', 'Waiting for the first real action.'));
    for (const item of steps) {
      const row = el('div', `zpa-step ${item.state || ''}`);
      row.append(el('b', '', markFor(item.state)), el('span', '', item.label || 'Step'));
      main.appendChild(row);
      if (item.error) main.appendChild(el('div', 'zpa-error', item.error));
      else if (item.detail) main.appendChild(el('div', 'zpa-muted', item.detail));
    }

    if (task.terminal && task.terminal.length) {
      main.appendChild(el('div', 'zpa-label', 'Terminal output'));
      const term = el('div', 'zpa-term');
      for (const line of task.terminal) {
        const row = el('div', /^\$ /.test(line) ? 'cmd' : /error|failed|\[exit [1-9]/i.test(line) ? 'bad' : '', line);
        term.appendChild(row);
      }
      term.addEventListener('scroll', () => {
        termAtBottom = term.scrollTop + term.clientHeight >= term.scrollHeight - 24;
      });
      main.appendChild(term);
      if (termAtBottom) term.scrollTop = term.scrollHeight;
    }

    if (task.verification && task.verification.length) {
      main.appendChild(el('div', 'zpa-label', 'Verification'));
      for (const check of task.verification) {
        const row = el('div', `zpa-check ${check.ok ? 'ok' : 'no'}`);
        row.append(el('b', '', check.ok ? '✓' : '!'), el('span', '', `${check.check} — ${check.detail || ''}`));
        main.appendChild(row);
      }
    }

    // Shown whenever a server is actually up -- including after the build
    // finishes, since the point of the build was to look at the result.
    if (task.preview_url && task.current_status !== 'CANCELLED') {
      main.appendChild(el('div', 'zpa-label', `Browser preview: ${task.preview_url}`));
      const wrap = el('div', 'zpa-preview');
      const frame = document.createElement('iframe');
      frame.src = task.preview_url;
      frame.title = 'Live preview of the project being built';
      wrap.appendChild(frame); main.appendChild(wrap);
    }
  }

  // --- legacy single-file project rendering ------------------------------

  async function selectDestination(project, destination) {
    try {
      const response = await fetch('/api/projects/destination', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:project.name, destination}) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Could not save the destination.');
      projects.set(result.project.id, result.project); activeId = result.project.id; activeKind = 'project'; render();
      // This is an explicit owner click, not an autonomous retry.  The
      // dashboard's normal conversation path receives it and continues the
      // already-requested project with the confirmed full path.
      window.dispatchEvent(new CustomEvent('zeno-project-destination-selected', { detail: result.project }));
    } catch (error) {
      side.appendChild(el('div', 'zpa-error', String(error.message || error)));
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

  function renderProject(project) {
    title.textContent = project.name || 'Untitled project'; state.textContent = project.state || 'WAITING';
    state.className = 'zpa-state' + (project.state === 'FAILED' ? ' bad' : '');
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

  async function websitePost(url, location) {
    const response = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({location}) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Website Studio action failed.');
    return result;
  }

  function renderWebsiteStudio(site) {
    title.textContent = 'Website Studio';
    state.textContent = site ? (site.status || 'READY').toUpperCase() : 'EMPTY';
    state.className = 'zpa-state';
    side.append(el('div', 'zpa-label', 'Website projects'), el('div', 'zpa-value', `${websiteProjects.size} registered`));
    for (const item of websiteProjects.values()) {
      const select = el('button', 'zpa-choice', item.project_name || item.location);
      select.type = 'button';
      select.addEventListener('click', () => { activeId = item.location; activeKind = 'website'; render(); });
      side.appendChild(select);
    }
    if (!site) {
      main.appendChild(el('div', 'zpa-muted', 'No registered website projects. Build one through ZENO to see it here.'));
      return;
    }
    side.append(el('div', 'zpa-label', 'Framework'), el('div', 'zpa-value', site.framework || 'Unknown'));
    side.append(el('div', 'zpa-label', 'Location'), el('div', 'zpa-file', site.location || ''));
    const preview = site.preview || null;
    if (preview) {
      side.append(el('div', 'zpa-label', 'Managed preview'), el('div', 'zpa-value', preview.url || ''));
      side.append(el('div', 'zpa-muted', `port ${preview.port || '—'} · ${preview.mode || 'server'} · ${preview.pid ? 'PID ' + preview.pid : preview.thread_id ? 'thread ' + preview.thread_id : 'managed'}`));
    } else side.appendChild(el('div', 'zpa-muted', 'No preview server is running.'));
    const actions = el('div', 'zpa-choice-row'); const note = el('div', 'zpa-muted', '');
    const folder = el('button', 'zpa-choice', 'Open Folder');
    const inspect = el('button', 'zpa-choice', 'Static Check');
    const visual = el('button', 'zpa-choice', 'Visual Check'); visual.disabled = !preview;
    const fail = (error) => { note.className = 'zpa-error'; note.textContent = String(error.message || error); };
    folder.addEventListener('click', () => websitePost('/api/website/open-folder', site.location).then(r => { note.textContent = r.message || ''; }).catch(fail));
    inspect.addEventListener('click', () => websitePost('/api/website/inspect', site.location).then(r => { note.textContent = (r.findings || []).length ? r.findings.join(' · ') : 'No basic static findings.'; }).catch(fail));
    visual.addEventListener('click', () => { visual.disabled = true; note.className = 'zpa-muted'; note.textContent = 'Rendering desktop and mobile evidence…'; websitePost('/api/website/visual-inspect', site.location).then(r => { const overflow = (r.captures || []).filter(c => c.horizontal_overflow).length; note.textContent = `Captured ${(r.captures || []).length} viewport(s); horizontal overflow in ${overflow}.`; }).catch(fail).finally(() => { visual.disabled = !site.preview; }); });
    actions.append(folder, inspect, visual); side.append(actions, note);
    main.appendChild(el('div', 'zpa-label', 'Project pages'));
    for (const page of site.pages || []) main.appendChild(el('div', 'zpa-file', page));
    main.appendChild(el('div', 'zpa-muted', 'Visual Check captures real local preview screenshots and layout measurements; it does not make an aesthetic success claim.'));
  }

  function render() {
    side.replaceChildren(); main.replaceChildren();
    if (activeKind === 'website') { renderWebsiteStudio(currentWebsite()); return; }
    // A running build outranks the older project feed: it is the thing the
    // owner is actually watching happen.
    const task = currentTask();
    if (task && (activeKind === 'task' || !currentProject())) { renderTask(task); return; }
    const project = currentProject();
    if (!project) {
      title.textContent = 'Live Activity'; state.textContent = 'WAITING'; state.className = 'zpa-state';
      side.appendChild(el('div', 'zpa-muted', 'No project is active.'));
      return;
    }
    renderProject(project);
  }

  function consumeEvent(update) {
    const type = String(update?.type || ''); const payload = update?.payload || {};
    if (type === 'build.task' && payload.task) {
      tasks.set(payload.task.task_id, payload.task); activeId = payload.task.task_id; activeKind = 'task';
      if (overlay.classList.contains('open')) render();
      return true;
    }
    if (type === 'project.activity' && payload.project) {
      projects.set(payload.project.id, payload.project); activeId = payload.project.id; activeKind = 'project';
      if (overlay.classList.contains('open')) render();
      return true;
    }
    if (type === 'ui.workspace_code' && payload.project) {
      const project = [...projects.values()].find(item => item.name === payload.project);
      if (project) {
        project.preview = { file: payload.file || '', content: payload.content || '' };
        project.files = payload.files || project.files;
        if (overlay.classList.contains('open')) render();
      }
      return !!project;
    }
    if (type.startsWith('website.') && payload.location) {
      const existing = websiteProjects.get(payload.location) || {};
      websiteProjects.set(payload.location, { ...existing, ...payload });
      if (activeKind === 'website' && overlay.classList.contains('open')) render();
      return true;
    }
    return false;
  }

  async function refresh() {
    // One fetch on load so a panel opened mid-build shows real current
    // state. Everything after this arrives as events -- there is no poll.
    try {
      const [projectData, taskData, websiteData] = await Promise.all([
        fetch('/api/projects/activity').then(r => r.json()).catch(() => ({})),
        fetch('/api/build/tasks').then(r => r.json()).catch(() => ({})),
        fetch('/api/website/projects').then(r => r.json()).catch(() => ({})),
      ]);
      for (const project of projectData.projects || []) projects.set(project.id, project);
      for (const task of taskData.tasks || []) tasks.set(task.task_id, task);
      for (const site of websiteData.projects || []) websiteProjects.set(site.location, site);
      const runningTask = [...tasks.values()].find(t => !DONE_STATES.includes(t.current_status));
      if (runningTask) { activeId = runningTask.task_id; activeKind = 'task'; }
      const pending = [...projects.values()].find(project => !['COMPLETED', 'FAILED'].includes(project.state));
      if (!runningTask && pending) { activeId = pending.id; activeKind = 'project'; }
      if (overlay.classList.contains('open')) render();
    } catch (_) { /* The activity panel remains dormant if the local API is unavailable. */ }
  }

  function openWebsiteStudio() { activeKind = 'website'; activeId = currentWebsite()?.location || ''; show(); }
  function dispose() { overlay.remove(); projects.clear(); tasks.clear(); websiteProjects.clear(); }
  return { consumeEvent, refresh, open: show, openWebsiteStudio, close: () => overlay.classList.remove('open'), dispose };
}
