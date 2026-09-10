// Test-only browser boundary. This does not render CSS, run native windows,
// simulate layout/animation interpolation, or replace character behavior.
export function createHarness({ maxCallbacks = 100000 } = {}) {
  let now = 0, nextId = 1, callbacks = 0;
  const timers = new Map(), eventTargets = [], descriptors = new Map();
  let installed = false;

  function eventTarget() {
    const listeners = new Map();
    eventTargets.push(listeners);
    return {
      addEventListener(type, handler) {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type).add(handler);
      },
      removeEventListener(type, handler) { listeners.get(type)?.delete(handler); },
      dispatchEvent(event) {
        for (const handler of [...(listeners.get(event.type) || [])]) handler(event);
        return true;
      },
    };
  }

  function element(tagName) {
    const classes = new Set(), props = new Map(), selected = new Map();
    const el = {
      ...eventTarget(), tagName, id: '', innerHTML: '', textContent: '',
      children: [], parentNode: null,
      rect: { left: 912, top: 476, width: 96, height: 128 },
      style: {
        setProperty(key, value) { props.set(key, String(value)); },
        getPropertyValue(key) { return props.get(key) || ''; },
        removeProperty(key) { const old = props.get(key) || ''; props.delete(key); return old; },
      },
      classList: {
        add(...names) { names.forEach(name => classes.add(name)); },
        remove(...names) { names.forEach(name => classes.delete(name)); },
        contains(name) { return classes.has(name); },
        toggle(name, force = !classes.has(name)) {
          if (force) classes.add(name); else classes.delete(name);
          return force;
        },
      },
      appendChild(child) {
        child.remove(); child.parentNode = el; el.children.push(child); return child;
      },
      remove() {
        if (el.parentNode) {
          const siblings = el.parentNode.children;
          siblings.splice(siblings.indexOf(el), 1);
          el.parentNode = null;
        }
      },
      querySelector(selector) {
        // Only this descendant is queried by the baseline runtime. Fail loudly
        // if integration introduces another DOM dependency needing real coverage.
        if (selector !== '.zc-eyes') throw new Error(`Unsupported test selector: ${selector}`);
        if (!el.innerHTML.includes('zc-eyes')) return null;
        if (!selected.has(selector)) selected.set(selector, element('div'));
        return selected.get(selector);
      },
      getBoundingClientRect() { return { ...el.rect }; },
      get offsetWidth() { return el.rect.width; },
    };
    return el;
  }

  const window = { ...eventTarget(), innerWidth: 1920, innerHeight: 1080 };
  const document = {
    ...eventTarget(), visibilityState: 'visible',
    head: element('head'), body: element('body'), createElement: element,
  };

  function schedule(kind, fn, delay, args) {
    const id = nextId++;
    const ms = Math.max(kind === 'interval' ? 1 : 0, Number(delay) || 0);
    timers.set(id, { id, kind, fn, args, at: now + ms, delay: ms });
    return id;
  }
  const cancel = id => timers.delete(id);
  const globals = {
    window, document, performance: { now: () => now },
    setTimeout: (fn, ms, ...args) => schedule('timeout', fn, ms, args),
    clearTimeout: cancel,
    setInterval: (fn, ms, ...args) => schedule('interval', fn, ms, args),
    clearInterval: cancel,
    requestAnimationFrame: fn => schedule('raf', fn, 16, []),
    cancelAnimationFrame: cancel,
  };

  return {
    window, document,
    roots: () => document.body.children.filter(el => el.id === 'zeno-character'),
    install() {
      if (installed) throw new Error('Harness already installed');
      for (const [key, value] of Object.entries(globals)) {
        descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
        Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
      }
      installed = true;
    },
    restore() {
      if (!installed) return;
      for (const [key, descriptor] of descriptors) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      descriptors.clear(); timers.clear(); installed = false;
    },
    advance(ms) {
      if (!Number.isFinite(ms) || ms < 0) throw new Error('Time must be finite and non-negative');
      const end = now + ms;
      let processed = 0;
      while (true) {
        let next;
        for (const timer of timers.values()) {
          if (timer.at <= end && (!next || timer.at < next.at || (timer.at === next.at && timer.id < next.id))) next = timer;
        }
        if (!next) break;
        if (++processed > maxCallbacks) throw new Error('Clock callback limit exceeded');
        now = next.at;
        if (next.kind === 'interval') next.at += next.delay;
        else timers.delete(next.id);
        callbacks++;
        next.fn(...(next.kind === 'raf' ? [now] : next.args));
      }
      now = end;
    },
    counts() {
      const byKind = { timeout: 0, interval: 0, raf: 0 };
      for (const timer of timers.values()) byKind[timer.kind]++;
      let listeners = 0;
      for (const target of eventTargets) for (const set of target.values()) listeners += set.size;
      return { timers: timers.size, ...byKind, listeners, callbacks };
    },
  };
}
