// Webcam hand control (MediaPipe Tasks Vision GestureRecognizer, which
// gives BOTH gesture names and 21 hand landmarks). Loaded on demand only
// when a hand feature is toggled on (always-on webcam = privacy). Two
// independent modes share the one camera + recognizer:
//
//   Gesture actions  -> Open_Palm=play/pause, Closed_Fist=mute,
//                       Thumb_Up=vol+, Thumb_Down=vol-, Victory=next
//                       (POST /api/gesture)
//   Mouse control    -> index-fingertip moves the cursor, pinch
//                       (thumb+index) = click (POST /api/mouse)
//
// Any camera can be selected (setCameraDevice). Honest note also told to
// the user: the webcam recognition itself could NOT be tested in the
// build environment (no camera there) -- it's off by default, wrapped so
// a load failure can't break the rest of REYES, and needs real-world
// verification. Model + WASM load from a CDN on first enable (needs net).

const MP_VERSION = "0.10.14";
let recognizer = null;
let stream = null;
let video = null;
let running = false;
let deviceId = null;

let gestureActionsOn = false;
let mouseControlOn = false;

// gesture-action debounce
let lastGesture = "";
let lastFireTime = 0;

// mouse smoothing / throttle / pinch state
let smoothX = 0.5, smoothY = 0.5;
let lastMouseSend = 0;
let pinching = false;

async function _loadRecognizer(say) {
  if (recognizer) return;
  say("loading hand model…");
  const vision = await import(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`);
  const { GestureRecognizer, FilesetResolver } = vision;
  const fileset = await FilesetResolver.forVisionTasks(
    `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`
  );
  recognizer = await GestureRecognizer.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath:
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
    },
    runningMode: "VIDEO",
    numHands: 1,
  });
}

async function _startCamera() {
  const constraints = { video: deviceId ? { deviceId: { exact: deviceId } } : { width: 640, height: 480 } };
  stream = await navigator.mediaDevices.getUserMedia(constraints);
  video = document.createElement("video");
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;
  video.srcObject = stream;
  await video.play();
}

function _stopCamera() {
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  if (video) { video.srcObject = null; video = null; }
}

async function _ensureRunning(say) {
  if (running) return true;
  if (!gestureActionsOn && !mouseControlOn) return false;
  try {
    await _loadRecognizer(say);
    await _startCamera();
    running = true;
    say("camera on — show your hand");
    _loop(say);
    return true;
  } catch (e) {
    say("hand control failed: " + (e && e.message ? e.message : e));
    _stopCamera();
    running = false;
    return false;
  }
}

function _stopIfIdle(say) {
  if (gestureActionsOn || mouseControlOn) return;
  running = false;
  _stopCamera();
  if (say) say("camera off");
}

function _loop(say) {
  if (!running) return;
  try {
    if (video && video.readyState >= 2) {
      const res = recognizer.recognizeForVideo(video, performance.now());
      const hands = res && res.landmarks && res.landmarks.length ? res.landmarks[0] : null;

      if (mouseControlOn && hands) _handleMouse(hands, say);

      if (gestureActionsOn && res.gestures && res.gestures.length && res.gestures[0].length) {
        const g = res.gestures[0][0];
        if (g.score > 0.6 && g.categoryName && g.categoryName !== "None") _fireGesture(g.categoryName, say);
      }
    }
  } catch (e) { /* one bad frame must not kill the loop */ }
  requestAnimationFrame(() => _loop(say));
}

function _dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

function _handleMouse(hands, say) {
  const idx = hands[8];   // index fingertip
  const thumb = hands[4]; // thumb tip
  if (!idx) return;
  // mirror X (selfie view), amplify around center so edges are reachable
  const gain = 1.5;
  let nx = (1 - idx.x - 0.5) * gain + 0.5;
  let ny = (idx.y - 0.5) * gain + 0.5;
  nx = Math.max(0, Math.min(1, nx));
  ny = Math.max(0, Math.min(1, ny));
  smoothX = smoothX + (nx - smoothX) * 0.45;
  smoothY = smoothY + (ny - smoothY) * 0.45;

  // pinch = click (rising edge)
  const pinchDist = thumb ? _dist(idx, thumb) : 1;
  const nowPinch = pinchDist < 0.05;
  let click = false;
  if (nowPinch && !pinching) { click = true; if (say) say("👆 click"); }
  pinching = nowPinch;

  const now = performance.now();
  if (now - lastMouseSend < 30 && !click) return; // ~30fps, but always send a click
  lastMouseSend = now;
  fetch("/api/mouse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x: smoothX, y: smoothY, click }),
  }).catch(() => {});
}

function _fireGesture(name, say) {
  const now = performance.now();
  if (now - lastFireTime < 800) return;
  if (name === lastGesture && now - lastFireTime < 1600) return;
  lastGesture = name;
  lastFireTime = now;
  fetch("/api/gesture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gesture: name }),
  })
    .then((r) => r.json())
    .then((d) => { if (say) say(d.ok ? "✋ " + name : name + " (unmapped)"); })
    .catch(() => {});
}

// ---- public API ----
export async function enableGestureActions(on, onStatus) {
  gestureActionsOn = on;
  if (on) return await _ensureRunning(onStatus || (() => {}));
  _stopIfIdle(onStatus);
  return true;
}

export async function enableMouseControl(on, onStatus) {
  mouseControlOn = on;
  if (on) return await _ensureRunning(onStatus || (() => {}));
  _stopIfIdle(onStatus);
  return true;
}

export async function listCameras() {
  try {
    // labels are only populated after camera permission has been granted once
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "videoinput").map((d) => ({ deviceId: d.deviceId, label: d.label || "Camera" }));
  } catch (e) { return []; }
}

export async function setCameraDevice(id, onStatus) {
  deviceId = id || null;
  if (running) { // hot-swap the camera
    _stopCamera();
    try { await _startCamera(); } catch (e) { if (onStatus) onStatus("camera switch failed: " + e.message); }
  }
}

export function stopAll(onStatus) {
  gestureActionsOn = false;
  mouseControlOn = false;
  _stopIfIdle(onStatus);
}
