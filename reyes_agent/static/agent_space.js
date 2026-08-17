// ZENO Agent Space: a lightweight view over /api/agent-space.
// Business state stays on the server. This module owns only selected card,
// visible mode and one open-only health refresh timer.

let stylesReady = false;

function addStyles() {
  if (stylesReady) return;
  stylesReady = true;
  const style = document.createElement('style');
  style.textContent = `
    #subspace-overlay{width:min(96vw,1180px);height:min(90vh,790px);background:radial-gradient(circle at 50% 20%,rgba(76,67,161,.18),transparent 42%),linear-gradient(155deg,#070a16,#0a1021 62%,#080b14);border-color:rgba(113,155,255,.38);box-shadow:0 30px 90px rgba(0,0,0,.66),0 0 42px rgba(92,91,230,.16)}
    .as-modes{display:flex;gap:5px;flex-wrap:wrap}.as-mode{padding:5px 9px;border:1px solid rgba(123,155,224,.24);border-radius:999px;background:rgba(20,27,52,.72);color:#91a1c2;font:700 9px system-ui;letter-spacing:.05em;cursor:pointer}.as-mode.active{color:#f1f5ff;border-color:#719bff;background:rgba(83,102,190,.28)}
    #subspace-body{position:relative;background-image:radial-gradient(circle,rgba(139,174,255,.25) 0 1px,transparent 1.5px);background-size:43px 43px}
    .as-shell{min-height:100%;padding:12px 16px 18px}.as-masterline{text-align:center;color:#8ea0c5;font:10px system-ui;letter-spacing:.09em;text-transform:uppercase}.as-masterline b{color:#dce8ff}.as-deck{display:grid;grid-template-columns:44px minmax(120px,190px) minmax(230px,360px) minmax(120px,190px) 44px;gap:12px;align-items:center;justify-content:center;min-height:280px;padding:12px 0}.as-arrow{width:40px;height:40px;border:1px solid rgba(125,160,235,.35);border-radius:50%;background:rgba(9,15,32,.8);color:#d9e6ff;font-size:20px;cursor:pointer}.as-card{--accent:#719bff;min-width:0;padding:14px 12px;border:1px solid color-mix(in srgb,var(--accent) 36%,#283556);border-radius:20px;background:linear-gradient(165deg,color-mix(in srgb,var(--accent) 11%,#10162a),rgba(6,10,22,.96));color:#eaf1ff;text-align:center;box-shadow:0 14px 36px rgba(0,0,0,.35);transition:transform .24s ease,opacity .24s ease,border-color .24s ease}.as-card.side{transform:scale(.82);opacity:.62;cursor:pointer}.as-card.center{transform:scale(1);border-color:color-mix(in srgb,var(--accent) 72%,white);box-shadow:0 18px 55px rgba(0,0,0,.5),0 0 30px color-mix(in srgb,var(--accent) 25%,transparent)}.as-planet{width:92px;height:92px;margin:0 auto 11px;border-radius:50%;background:radial-gradient(circle at 32% 26%,#eef6ff 0 4%,color-mix(in srgb,var(--accent) 70%,white) 12%,var(--accent) 44%,color-mix(in srgb,var(--accent) 45%,#080b18) 72%,#060811 100%);box-shadow:inset -18px -17px 26px rgba(0,0,0,.38),0 0 24px color-mix(in srgb,var(--accent) 44%,transparent);position:relative}.as-planet::after{content:'';position:absolute;inset:-10px -25px;border:1px solid color-mix(in srgb,var(--accent) 38%,transparent);border-radius:50%;transform:rotate(-13deg)}.as-card.side .as-planet{width:58px;height:58px}.as-card h3{margin:4px 0;font:800 16px system-ui;letter-spacing:.12em}.as-role{height:30px;color:#91a2c5;font:10px/1.35 system-ui}.as-state{display:inline-flex;margin-top:8px;padding:4px 8px;border-radius:999px;background:color-mix(in srgb,var(--accent) 15%,#0b1020);color:color-mix(in srgb,var(--accent) 70%,white);font:800 9px system-ui;letter-spacing:.08em}.as-task{margin-top:8px;color:#c8d4ed;font:10px/1.35 system-ui;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.as-roster{display:flex;gap:7px;padding:9px 3px 14px;overflow-x:auto;scrollbar-width:thin}.as-roster button{--accent:#719bff;flex:0 0 auto;min-width:80px;padding:7px 9px;border:1px solid rgba(110,144,210,.2);border-radius:11px;background:rgba(9,15,30,.76);color:#9eadc8;font:700 9px system-ui;cursor:pointer}.as-roster button.selected{border-color:var(--accent);color:#edf4ff;box-shadow:0 0 12px color-mix(in srgb,var(--accent) 24%,transparent)}.as-dot{display:inline-block;width:7px;height:7px;margin-right:5px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent)}
    .as-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:9px}.as-panel{padding:12px;border:1px solid rgba(113,147,215,.17);border-radius:14px;background:rgba(8,14,29,.78)}.as-panel h4{margin:0 0 8px;color:#e6eeff;font:800 11px system-ui;letter-spacing:.08em}.as-panel p{margin:5px 0;color:#aebbd4;font:10px/1.45 system-ui}.as-panel b{color:#f0f4ff}.as-flow{display:grid;gap:6px}.as-event{display:grid;grid-template-columns:55px minmax(105px,160px) 1fr auto;gap:8px;align-items:center;padding:8px 9px;border-left:2px solid #566fbe;border-radius:7px;background:rgba(16,24,45,.7);font:10px system-ui}.as-event time{color:#71809e}.as-event strong{color:#dce7ff}.as-event span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aebbd4}.as-event em{color:#8fc2ff;font:700 8px system-ui}.as-worker{display:grid;grid-template-columns:1fr auto;gap:7px;padding:7px 0;border-bottom:1px solid rgba(120,150,210,.1)}.as-worker:last-child{border:0}.as-worker small{display:block;color:#8594b1;margin-top:2px}.as-toolset{max-height:68px;overflow:auto;color:#8698bb!important}.as-approval{border-color:#e6a84a;background:rgba(91,59,20,.2)}.as-empty{padding:42px 10px;text-align:center;color:#8d9bb6;font:12px system-ui}#subspace-detail{max-height:180px;overflow:auto;background:rgba(5,9,19,.9)}
    @media(max-width:760px){.as-deck{grid-template-columns:38px minmax(210px,1fr) 38px}.as-card.side{display:none}.as-event{grid-template-columns:45px 115px 1fr}.as-event em{display:none}.as-modes{display:none}}
    @media(prefers-reduced-motion:reduce){.as-card{transition:none}}
  `;
  document.head.appendChild(style);
}

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;',
})[char]);

export function createAgentSpace({ overlay, body, detail, summary, modeButtons = [] } = {}) {
  if (!overlay || !body || !detail) throw new Error('Agent Space elements are missing');
  addStyles();
  const state = { data:null, selected:'zeno', mode:'space', timer:null, refreshTimer:null, clickTimer:null, open:false };

  const roster = () => state.data ? [state.data.master, ...(state.data.agents || [])] : [];
  const selectedIndex = () => Math.max(0, roster().findIndex((agent) => agent.id === state.selected));
  const select = (id, showDetail = false) => {
    if (!roster().some((agent) => agent.id === id)) return;
    state.selected = id;
    if (showDetail) state.mode = 'detail';
    render();
  };
  const card = (agent, where) => {
    if (!agent) return '<div></div>';
    const task = agent.current_task || (agent.id === 'zeno' ? 'Final authority and owner-facing synthesis' : 'No active task');
    return `<button class="as-card ${where}" style="--accent:${esc(agent.color || '#719bff')}" data-agent="${esc(agent.id)}"><i class="as-planet"></i><h3>${esc(agent.name)}</h3><div class="as-role">${esc(agent.role || '')}</div><div class="as-state">${esc(agent.state || 'REGISTERED')}</div><div class="as-task">${esc(task)}</div></button>`;
  };
  const rosterBar = () => `<div class="as-roster">${roster().map((agent) => `<button style="--accent:${esc(agent.color)}" class="${agent.id === state.selected ? 'selected' : ''}" data-agent="${esc(agent.id)}"><i class="as-dot"></i>${esc(agent.name)} · ${esc(agent.state || 'REGISTERED')}</button>`).join('')}</div>`;

  function spaceView() {
    const all = roster(), index = selectedIndex(), total = all.length;
    const previous = all[(index - 1 + total) % total], current = all[index], next = all[(index + 1) % total];
    return `<div class="as-masterline"><b>ZENO</b> remains executive, policy controller and final synthesizer</div><div class="as-deck"><button class="as-arrow" data-nav="-1" aria-label="Previous agent">‹</button>${card(previous,'side')}${card(current,'center')}${card(next,'side')}<button class="as-arrow" data-nav="1" aria-label="Next agent">›</button></div>${rosterBar()}`;
  }
  function activeView() {
    const active = (state.data.agents || []).filter((agent) => agent.routed || agent.speaking || agent.active_task_count);
    if (!active.length) return '<div class="as-empty">No specialist is executing a task. ZENO is ready and the registered roster remains lazy.</div>' + rosterBar();
    return `<div class="as-grid">${active.map((agent) => `<button class="as-panel" data-agent="${esc(agent.id)}"><h4><i class="as-dot" style="--accent:${esc(agent.color)}"></i>${esc(agent.name)} · ${esc(agent.state)}</h4><p><b>Owner:</b> ${esc(agent.name)} · <b>Delegated by:</b> ZENO</p><p>${esc(agent.current_task || 'Queued work')}</p><p>Queue ${Number(agent.queue_depth || 0)} · ${Number(agent.tasks_completed || 0)} completed · ${Number(agent.tasks_failed || 0)} failed</p></button>`).join('')}</div>`;
  }
  function councilView() {
    const council = state.data.council || {}, ids = council.participants || [];
    const members = ids.map((id) => (state.data.agents || []).find((agent) => agent.id === id)).filter(Boolean);
    return `<div class="as-panel"><h4>COUNCIL ${council.active ? 'ACTIVE' : 'STANDBY'}</h4><p>ZENO is the final authority. ${council.current_speaker ? `${esc(council.current_speaker.toUpperCase())} is speaking.` : 'No agent is speaking.'}</p></div><div class="as-grid">${members.map((agent) => card(agent,'center')).join('') || '<div class="as-empty">No real Council participants are active. Agents appear here only after a lifecycle event.</div>'}</div>`;
  }
  function flowView() {
    const events = (state.data.events || []).slice(-50).reverse();
    const approvals = state.data.approvals || [];
    return `${approvals.map((item) => `<div class="as-panel as-approval"><h4>WAITING APPROVAL · ${esc(item.tool)}</h4><p>${esc(item.description)}</p><p>Approval #${Number(item.id)} is in the real ZENO confirmation queue.</p></div>`).join('')}<div class="as-flow">${events.map((event) => `<div class="as-event"><time>${esc(String(event.time || '').slice(11,16))}</time><strong>${esc(String(event.source || '').toUpperCase())} → ${esc(String(event.target || '').toUpperCase())}</strong><span>${esc(event.summary || event.type)}</span><em>${esc(String(event.status || '').toUpperCase())}</em></div>`).join('') || '<div class="as-empty">No agent handoff has been recorded yet.</div>'}</div>`;
  }
  function detailView() {
    const agent = roster().find((item) => item.id === state.selected) || state.data.master;
    if (agent.id === 'zeno') return `<div class="as-panel"><h4>ZENO · EXECUTIVE ORCHESTRATOR</h4><p>Master router, policy controller, owner-facing voice and final synthesizer.</p><p>Current state: <b>${esc(agent.state)}</b></p><p>Specialists do not replace ZENO's authority.</p></div>${rosterBar()}`;
    const workers = agent.workers || [];
    return `<div class="as-grid"><section class="as-panel"><h4>${esc(agent.name)} · ${esc(agent.state)}</h4><p>${esc(agent.role)}</p><p>${esc(agent.description || 'Registered specialist')}</p><p><b>Current task:</b> ${esc(agent.current_task || 'None')}</p><p><b>Health:</b> ${agent.healthy ? 'healthy' : 'degraded'} · heartbeat ${agent.heartbeat_age_s == null ? 'not started' : `${Number(agent.heartbeat_age_s)}s ago`}</p><p><b>Voice:</b> ${agent.voice?.configured ? (agent.voice.own_voice ? 'own configured voice' : 'configured fallback') : 'not configured'}</p></section><section class="as-panel"><h4>WORKERS · ${workers.length}</h4>${workers.map((worker) => `<div class="as-worker"><span><b>${esc(String(worker.name).toUpperCase())}</b><small>${esc(worker.role || '')}</small><small class="as-toolset">${esc((worker.tools || []).join(', ') || 'reasoning only')}</small></span><b>${esc(worker.status || 'UNKNOWN')}</b></div>`).join('') || '<p>No worker team is registered for this agent.</p>'}</section><section class="as-panel"><h4>ALLOWED TOOLS · ${(agent.allowed_tools || []).length}</h4><p class="as-toolset">${esc((agent.allowed_tools || []).join(', ') || 'No direct tool capability declared')}</p><p><b>Last task:</b> ${esc(agent.last_task || 'None')}</p><p><b>Last error:</b> ${esc(agent.last_error || 'None')}</p></section></div>${rosterBar()}`;
  }

  function renderDetailFooter() {
    const agent = roster().find((item) => item.id === state.selected) || state.data?.master;
    if (!agent) { detail.textContent = 'Select an agent to inspect it.'; return; }
    detail.innerHTML = `<div class="sd-row"><span>Focus</span><span><b>${esc(agent.name)}</b> · ${esc(agent.role || '')}</span></div><div class="sd-row"><span>State</span><span>${esc(agent.state || 'REGISTERED')}</span></div><div class="sd-row"><span>Task</span><span>${esc(agent.current_task || 'No active task')}</span></div>`;
  }
  function bind() {
    body.querySelectorAll('[data-agent]').forEach((element) => {
      element.addEventListener('click', () => {
        clearTimeout(state.clickTimer);
        state.clickTimer = setTimeout(() => {
          state.clickTimer = null;
          select(element.dataset.agent);
        }, 500);
      });
      element.addEventListener('dblclick', () => {
        clearTimeout(state.clickTimer); state.clickTimer = null;
        select(element.dataset.agent, true);
      });
    });
    body.querySelectorAll('[data-nav]').forEach((element) => element.addEventListener('click', () => {
      const all = roster(), next = (selectedIndex() + Number(element.dataset.nav) + all.length) % all.length;
      select(all[next].id);
    }));
  }
  function render() {
    if (!state.open || !state.data) return;
    modeButtons.forEach((button) => button.classList.toggle('active', button.dataset.agentSpaceMode === state.mode));
    const views = { space:spaceView, active:activeView, council:councilView, flow:flowView, detail:detailView };
    body.innerHTML = `<div class="as-shell">${(views[state.mode] || spaceView)()}</div>`;
    const stats = state.data.summary || {};
    summary.textContent = `${Number(stats.active || 0)} active · ${Number(stats.alive || 0)}/${Number(stats.registered || 0)} alive · ${Number(stats.workers || 0)} workers · ${Number(stats.pending_approvals || 0)} approvals`;
    renderDetailFooter(); bind();
  }
  async function refresh() {
    if (!state.open) return;
    const response = await fetch('/api/agent-space?limit=70', {cache:'no-store'});
    if (!response.ok) throw new Error(`Agent Space request failed (${response.status})`);
    state.data = await response.json();
    if (!roster().some((agent) => agent.id === state.selected)) state.selected = state.data.active_specialist || 'zeno';
    render();
  }
  function scheduleRefresh() {
    clearTimeout(state.refreshTimer);
    state.refreshTimer = setTimeout(() => { state.refreshTimer = null; refresh().catch(() => {}); }, 180);
  }
  async function open(focus = '', mode = 'space') {
    state.open = true; state.mode = mode || 'space'; if (focus) state.selected = String(focus).toLowerCase();
    overlay.classList.add('open'); body.innerHTML = '<div class="as-empty">Reading the live agent runtime…</div>';
    try { await refresh(); } catch (error) { body.innerHTML = `<div class="as-empty">${esc(error.message)}</div>`; }
    clearInterval(state.timer);
    state.timer = setInterval(() => { if (!document.hidden && state.open) refresh().catch(() => {}); }, 6000);
  }
  function close() {
    state.open = false; clearInterval(state.timer); clearTimeout(state.refreshTimer); clearTimeout(state.clickTimer);
    state.timer = null; state.refreshTimer = null; state.clickTimer = null; overlay.classList.remove('open');
    body.replaceChildren(); detail.textContent = 'Select an agent to inspect it.';
  }
  function ingest(event) {
    if (!state.open) return;
    const type = String(event?.type || '');
    if (type.startsWith('agent.') || type.startsWith('confirmation.')) scheduleRefresh();
  }
  modeButtons.forEach((button) => button.addEventListener('click', () => { state.mode = button.dataset.agentSpaceMode; render(); }));
  return { open, close, refresh, ingest, select, state: () => ({open:state.open,mode:state.mode,selected:state.selected,agents:state.data?.agents?.length ?? null}) };
}
