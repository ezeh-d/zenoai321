import { WorkspaceRevisionBuffer } from './client.js';

function element(documentRef, tag, className = '', text = '') {
  const node = documentRef.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
function stateLabel(value) {
  return String(value || '').replaceAll('_', ' ').toLowerCase();
}

export function createWorkspaceShell({ fetchImpl = globalThis.fetch?.bind(globalThis),
                                       documentRef = globalThis.document } = {}) {
  if (typeof fetchImpl !== 'function') throw new Error('Workspace shell needs fetch.');
  const buffer = new WorkspaceRevisionBuffer();
  const controllers = new Set();
  const controlled = new Map();
  let disposed = false;
  let framePending = false;
  let searchSequence = 0;
  let root = null;
  let panelHost = null;
  let activityHost = null;

  if (documentRef) {
    root = documentRef.getElementById('zeno-workspace-root');
    if (!root) {
      root = element(documentRef, 'aside', 'zeno-workspace-root');
      root.id = 'zeno-workspace-root';
      root.setAttribute('aria-live', 'polite');
      root.setAttribute('aria-label', 'ZENO live workspace');
      panelHost = element(documentRef, 'div', 'zeno-workspace-panels');
      activityHost = element(documentRef, 'div', 'zeno-workspace-activities');
      root.append(panelHost, activityHost);
      documentRef.body.appendChild(root);
    } else {
      panelHost = root.querySelector('.zeno-workspace-panels');
      activityHost = root.querySelector('.zeno-workspace-activities');
    }
  }

  async function request(url, options = {}) {
    if (disposed) throw new Error('Workspace shell is disposed.');
    const ownController = options.signal ? null : new AbortController();
    if (ownController) controllers.add(ownController);
    try {
      const response = await fetchImpl(url, {
        ...options,
        signal: options.signal || ownController?.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Workspace request failed.');
      return payload;
    } finally {
      if (ownController) controllers.delete(ownController);
    }
  }

  function closeControlled(panelId) {
    const entry = controlled.get(panelId);
    if (!entry) return;
    if (entry.kind === 'dom') entry.value?.classList?.remove('open');
    if (entry.kind === 'module') entry.value?.close?.();
    controlled.delete(panelId);
  }

  function activateExternal(panel, definition) {
    const component = String(definition?.component || '');
    if (component.startsWith('dom:')) {
      const target = documentRef?.querySelector(component.slice(4));
      if (target) {
        target.classList.add('open');
        controlled.set(panel.panel_id, { kind: 'dom', value: target });
      }
      return true;
    }
    if (!component.startsWith('module:')) return false;
    const spec = component.slice(7);
    const [url, exportName = 'default'] = spec.split('#');
    const existing = panel.panel_id === 'activity' ? globalThis.zenoActivity : null;
    if (existing) {
      existing.open?.();
      controlled.set(panel.panel_id, { kind: 'module', value: existing });
      return true;
    }
    import(url).then((module) => {
      if (disposed || !(buffer.state.panels || []).some(
        (item) => item.panel_id === panel.panel_id && item.state !== 'CLOSED')) return;
      const factory = module[exportName];
      if (typeof factory !== 'function') return;
      const instance = factory();
      if (panel.panel_id === 'activity') globalThis.zenoActivity = instance;
      instance.open?.();
      controlled.set(panel.panel_id, { kind: 'module', value: instance });
    }).catch(() => {});
    return true;
  }

  function makeButton(label, action, panel) {
    const button = element(documentRef, 'button', 'zeno-workspace-action', label);
    button.type = 'button';
    button.addEventListener('click', () => {
      void panelAction(panel.panel_id, action, panel.context || {}, panel.correlation_id || '',
                       action === 'dock' ? 'right' : '');
    });
    return button;
  }

  function renderActivityRows(container, filter = '') {
    const rows = (buffer.state.activities || []).filter(
      (item) => !filter || item.category === filter || item.panel_target === filter);
    if (!rows.length) {
      container.appendChild(element(documentRef, 'div', 'zeno-workspace-empty', 'No live activity.'));
      return;
    }
    for (const item of rows.slice(0, 20)) {
      const row = element(documentRef, 'article', `zeno-workspace-row ${stateLabel(item.status)}`);
      row.append(
        element(documentRef, 'strong', '', item.title || 'Activity'),
        element(documentRef, 'span', '', stateLabel(item.status)),
        element(documentRef, 'p', '', item.safe_detail || ''),
      );
      container.appendChild(row);
    }
  }

  function renderBuiltin(container, definition) {
    const kind = String(definition.component || '').slice(8);
    if (kind === 'activity') {
      renderActivityRows(container, definition.id);
    } else if (kind === 'history') {
      for (const item of (buffer.state.history || []).slice(0, 25)) {
        const row = element(documentRef, 'article', 'zeno-workspace-row');
        row.append(element(documentRef, 'strong', '', item.request_summary || 'Recorded task'),
                   element(documentRef, 'span', '', stateLabel(item.status)),
                   element(documentRef, 'p', '', item.safe_result || ''));
        container.appendChild(row);
      }
    } else if (kind === 'health') {
      for (const item of (buffer.state.health || []).slice(0, 50)) {
        const row = element(documentRef, 'article', `zeno-workspace-row ${stateLabel(item.status)}`);
        row.append(element(documentRef, 'strong', '', item.name || 'Capability'),
                   element(documentRef, 'span', '', stateLabel(item.status)),
                   element(documentRef, 'p', '', item.reason || 'No evidence recorded yet.'));
        container.appendChild(row);
      }
    } else if (kind === 'search') {
      const form = element(documentRef, 'form', 'zeno-workspace-search');
      const input = element(documentRef, 'input');
      input.type = 'search'; input.placeholder = 'Search ZENO metadata';
      const results = element(documentRef, 'div', 'zeno-workspace-results');
      form.append(input, makeButton('Search', 'focus', { panel_id: definition.id, context: {} }));
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        void search(input.value).then((items) => {
          results.replaceChildren();
          for (const item of items) {
            const button = element(documentRef, 'button', 'zeno-workspace-result', item.title || item.target);
            button.type = 'button';
            button.addEventListener('click', () => void executeSearchResult(item));
            results.appendChild(button);
          }
        });
      });
      container.append(form, results);
    }
  }

  function render() {
    framePending = false;
    if (disposed || !documentRef || documentRef.hidden || !panelHost || !activityHost) return;
    const panels = buffer.state.panels || [];
    const activeIds = new Set(panels.map((item) => item.panel_id));
    for (const panelId of [...controlled.keys()]) {
      if (!activeIds.has(panelId)) closeControlled(panelId);
    }
    panelHost.replaceChildren();
    const definitions = new Map((buffer.state.panel_definitions || [])
      .map((item) => [item.id, item]));
    for (const panel of panels) {
      const definition = definitions.get(panel.panel_id);
      if (!definition || panel.state === 'CLOSED' || panel.state === 'BACKGROUND') continue;
      if (activateExternal(panel, definition)) continue;
      const card = element(documentRef, 'section', `zeno-workspace-panel ${stateLabel(panel.state)}`);
      const header = element(documentRef, 'header');
      header.append(element(documentRef, 'h2', '', definition.title || panel.panel_id),
                    makeButton('—', 'minimize', panel), makeButton('×', 'close', panel));
      const body = element(documentRef, 'div', 'zeno-workspace-panel-body');
      if (String(definition.component || '').startsWith('builtin:')) renderBuiltin(body, definition);
      else body.appendChild(element(documentRef, 'div', 'zeno-workspace-empty', 'Panel adapter unavailable.'));
      card.append(header, body);
      panelHost.appendChild(card);
    }
    activityHost.replaceChildren();
    renderActivityRows(activityHost);
    root?.classList.toggle('has-content', panels.length > 0 || (buffer.state.activities || []).length > 0);
  }

  function scheduleRender() {
    if (disposed || framePending) return;
    framePending = true;
    const schedule = globalThis.requestAnimationFrame || ((callback) => callback());
    schedule(render);
  }

  async function hydrate() {
    const snapshot = await request('/api/workspace/state');
    buffer.applySnapshot(snapshot);
    scheduleRender();
    return buffer.state;
  }

  function consumeEvent(event) {
    if (String(event?.type || '') === 'workspace.activity.changed') {
      globalThis.zenoActivity?.consumeEvent?.(event);
    }
    const changed = buffer.pushEvent(event);
    if (buffer.needsRehydrate) void hydrate().catch(() => {});
    else if (changed) scheduleRender();
    return changed;
  }

  async function panelAction(panelId, action, context = {}, correlationId = '', position = '') {
    const payload = await request(
      `/api/workspace/panels/${encodeURIComponent(panelId)}/${encodeURIComponent(action)}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context, correlation_id: correlationId, position }) },
    );
    await hydrate();
    return payload;
  }

  async function search(query, { signal } = {}) {
    const sequence = ++searchSequence;
    const payload = await request(
      `/api/workspace/search?q=${encodeURIComponent(String(query || '').slice(0, 200))}&limit=25`,
      signal ? { signal } : {},
    );
    return sequence === searchSequence ? (payload.results || []) : [];
  }

  async function executeSearchResult(result) {
    const action = String(result?.action || '');
    const target = String(result?.target || '');
    if (!target) return null;
    if (action === 'show' || action === 'show_panel') return panelAction(target, 'show');
    if (action === 'start_file_search') return panelAction('files', 'show', { query: target });
    if (action === 'show_history') return panelAction('history', 'show', { task_id: target });
    if (action === 'show_agent') return panelAction('agents', 'show', { agent: target });
    if (action === 'inspect_tool') return panelAction('tool-health', 'show', { query: target });
    if (action === 'search') return panelAction('search', 'show', { query: target });
    return null;
  }

  function onVisibility() { if (!documentRef?.hidden) scheduleRender(); }
  documentRef?.addEventListener?.('visibilitychange', onVisibility);

  function dispose() {
    disposed = true;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    for (const panelId of [...controlled.keys()]) closeControlled(panelId);
    documentRef?.removeEventListener?.('visibilitychange', onVisibility);
    root?.remove();
  }

  return { hydrate, consumeEvent, panelAction, search, executeSearchResult, dispose };
}
