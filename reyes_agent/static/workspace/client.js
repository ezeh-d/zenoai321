// Ordered client projection for the backend-authoritative workspace state.

function clone(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value ?? {}));
}
function upsert(rows, record, key) {
  const current = Array.isArray(rows) ? rows.slice() : [];
  const value = record?.[key];
  if (!value) return current;
  const index = current.findIndex((item) => item?.[key] === value);
  if (index >= 0) current[index] = clone(record);
  else current.unshift(clone(record));
  return current;
}

export class WorkspaceRevisionBuffer {
  constructor() {
    this.revision = 0;
    this.hydrated = false;
    this.needsRehydrate = false;
    this.buffer = [];
    this.state = {};
  }

  applySnapshot(snapshot) {
    this.state = clone(snapshot || {});
    for (const key of ['panels', 'panel_definitions', 'commands', 'activities', 'history', 'health']) {
      if (!Array.isArray(this.state[key])) this.state[key] = [];
    }
    this.revision = Number(snapshot?.revision || 0);
    this.state.revision = this.revision;
    this.hydrated = true;
    this.needsRehydrate = false;
    const pending = this.buffer.splice(0)
      .sort((a, b) => Number(a?.payload?.revision || 0) - Number(b?.payload?.revision || 0));
    for (const event of pending) this.pushEvent(event);
    return this.state;
  }

  pushEvent(event) {
    if (!String(event?.type || '').startsWith('workspace.')) return false;
    if (!this.hydrated) {
      this.buffer.push(clone(event));
      if (this.buffer.length > 100) this.buffer.shift();
      return true;
    }
    const next = Number(event?.payload?.revision || 0);
    if (!Number.isFinite(next) || next <= this.revision) return false;
    if (next !== this.revision + 1) {
      this.needsRehydrate = true;
      return false;
    }
    const payload = event.payload || {};
    if (event.type === 'workspace.panel.changed' && payload.panel) {
      const panel = payload.panel;
      if (panel.state === 'CLOSED') {
        this.state.panels = (this.state.panels || [])
          .filter((item) => item.instance_id !== panel.instance_id);
      } else {
        this.state.panels = upsert(this.state.panels, panel, 'instance_id');
      }
    } else if (event.type === 'workspace.activity.changed' && payload.activity) {
      this.state.activities = upsert(this.state.activities, payload.activity, 'activity_id');
    } else if (event.type === 'workspace.history.changed' && payload.history) {
      this.state.history = upsert(this.state.history, payload.history, 'task_id');
    } else if (event.type === 'workspace.health.changed' && payload.health) {
      this.state.health = upsert(this.state.health, payload.health, 'name');
    }
    this.revision = next;
    this.state.revision = next;
    return true;
  }
}
