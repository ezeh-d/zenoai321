// Shared drag + maximize for ALL ZENO workspace overlays (#*-overlay with a
// .ws-bar header). One delegated handler covers News, Coding, Agents, Council,
// Galaxy, Timeline, Situation, Subspace, Tool-Library -- and any overlay added
// later -- so movement/maximize live in ONE place, not per-panel.
//
// - grab the header -> drag the overlay; buttons inside the header stay clickable.
// - the overlay pins to left/top on first drag (transform cleared) and is
//   clamped so its header can never leave the viewport.
// - double-click the header (not a button) toggles maximize/restore.
// Pointer Events + pointer capture keep it smooth without per-pixel React work.

(function () {
  const overlayOf = (el) => {
    const bar = el.closest && el.closest(".ws-bar");
    return bar ? bar.parentElement : null;   // the #*-overlay wrapper
  };
  let drag = null;

  document.addEventListener("pointerdown", (e) => {
    const bar = e.target.closest && e.target.closest(".ws-bar");
    if (!bar) return;
    if (e.target.closest("button, input, select, textarea, a, .as-mode")) return; // controls
    const ov = bar.parentElement;
    if (!ov || !/-overlay$/.test(ov.id || "")) return;
    if (ov.classList.contains("ws-max")) return;             // don't drag while maximized
    const r = ov.getBoundingClientRect();
    ov.classList.add("ws-dragged");                          // clear centering transform
    ov.style.left = r.left + "px"; ov.style.top = r.top + "px";
    ov.style.width = r.width + "px"; ov.style.height = r.height + "px";
    drag = { ov, sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top };
    try { bar.setPointerCapture(e.pointerId); } catch (_e) {}
    e.preventDefault();
  }, true);

  document.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const W = window.innerWidth || 100000, H = window.innerHeight || 100000;
    const nx = Math.max(-drag.ov.offsetWidth + 80, Math.min(W - 80, drag.ox + e.clientX - drag.sx));
    const ny = Math.max(0, Math.min(H - 30, drag.oy + e.clientY - drag.sy));
    drag.ov.style.left = nx + "px";
    drag.ov.style.top = ny + "px";
  });

  const end = () => { drag = null; };
  document.addEventListener("pointerup", end);
  document.addEventListener("pointercancel", end);

  // double-click header -> maximize / restore
  document.addEventListener("dblclick", (e) => {
    const bar = e.target.closest && e.target.closest(".ws-bar");
    if (!bar || e.target.closest("button, input, select, textarea, a, .as-mode")) return;
    const ov = bar.parentElement;
    if (!ov || !/-overlay$/.test(ov.id || "")) return;
    if (ov.classList.contains("ws-max")) {
      ov.classList.remove("ws-max");                         // restore
    } else {
      // remember the floating geometry so restore returns to it
      ov.classList.add("ws-max");
    }
  });
})();
