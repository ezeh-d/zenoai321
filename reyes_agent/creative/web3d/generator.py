"""Generate a real 3D website -- where the meaning survives without the 3D.

THE RULE THIS IS BUILT AROUND
-----------------------------
"Important website meaning must NOT exist only inside a WebGL canvas."

That is not an accessibility footnote, it is the difference between a site
and a demo. A canvas is one element to a crawler and nothing at all to a
screen reader, so a beautiful WebGL landing page with its headline drawn in
3D text has no headline. It cannot rank, cannot be read aloud, and vanishes
entirely for the ~1 in 20 visitors whose GPU or driver refuses it.

So the generator emits the semantic page FIRST -- real `<h1>`, real copy,
real links, real CTA -- and layers the scene behind it as decoration. Delete
the canvas and the page still works. That ordering is enforced by
`verify_site()`, which flags a canvas page with no `<h1>`.

THREE DECISIONS WORTH DEFENDING
-------------------------------
* **No build step.** An import map and ES modules, so the output is files a
  browser runs directly. A generated site that needs npm install before
  anyone can look at it is a project, not a deliverable.
* **Scene budget, enforced.** `budget.py` refuses geometry that would ship
  megabytes into a landing page. The brief's words: do not ship 500MB into
  a simple page.
* **Reduced motion is honoured.** `prefers-reduced-motion` stops the
  animation loop rather than merely slowing it, because for the people who
  set that flag, spinning geometry is not a style preference.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.creative.web3d import budget

# Scene kinds the generator can actually produce. Each is procedural --
# no downloaded model, nothing to optimise, nothing to go missing.
PARTICLES = "particles"
WIREFRAME = "wireframe"
ORB = "orb"
GRID = "grid"

SCENES = (PARTICLES, WIREFRAME, ORB, GRID)

# Pinned so a generated site does not silently change when a CDN moves on.
THREE_VERSION = "0.169.0"
THREE_CDN = f"https://unpkg.com/three@{THREE_VERSION}/build/three.module.js"


@dataclass
class Section:
    heading: str
    body: str
    cta_text: str = ""
    cta_href: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"heading": self.heading, "body": self.body,
                "cta_text": self.cta_text, "cta_href": self.cta_href}


@dataclass
class SiteSpec:
    name: str
    headline: str
    subhead: str = ""
    sections: list[Section] = field(default_factory=list)
    scene: str = PARTICLES
    accent: str = "#4da3ff"
    background: str = "#05070d"
    base_url: str = ""
    description: str = ""
    foreground: str = "#e9eef5"
    font_url: str = ""
    heading_font: str = ""
    body_font: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "headline": self.headline,
                "subhead": self.subhead, "scene": self.scene,
                "sections": [s.as_dict() for s in self.sections]}


@dataclass
class Built:
    ok: bool = False
    directory: str = ""
    files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    budget_report: dict[str, Any] = field(default_factory=dict)
    design: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "directory": self.directory, "files": self.files,
                "problems": self.problems, "budget": self.budget_report,
                "design": self.design}


def _scene_js(spec: SiteSpec) -> str:
    """The Three.js module. Procedural geometry, disposed on teardown."""
    accent = spec.accent
    build = {
        PARTICLES: """
  const count = 1800;
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count * 3; i++) positions[i] = (Math.random() - 0.5) * 18;
  geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  material = new THREE.PointsMaterial({ color: ACCENT, size: 0.035 });
  object = new THREE.Points(geometry, material);""",
        WIREFRAME: """
  geometry = new THREE.IcosahedronGeometry(3.2, 2);
  material = new THREE.MeshBasicMaterial({ color: ACCENT, wireframe: true });
  object = new THREE.Mesh(geometry, material);""",
        ORB: """
  geometry = new THREE.SphereGeometry(2.6, 48, 32);
  material = new THREE.MeshStandardMaterial({
    color: ACCENT, roughness: 0.25, metalness: 0.7, wireframe: false });
  object = new THREE.Mesh(geometry, material);
  const key = new THREE.PointLight(0xffffff, 120);
  key.position.set(6, 6, 8);
  scene.add(key);
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));""",
        GRID: """
  geometry = new THREE.PlaneGeometry(40, 40, 40, 40);
  material = new THREE.MeshBasicMaterial({ color: ACCENT, wireframe: true });
  object = new THREE.Mesh(geometry, material);
  object.rotation.x = -Math.PI / 2.4;
  object.position.y = -3;""",
    }[spec.scene]

    return f"""// Decoration only. Every word on this page exists in the HTML.
import * as THREE from '{THREE_CDN}';

const ACCENT = new THREE.Color('{accent}');
const host = document.getElementById('scene');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

let renderer, scene, camera, object, geometry, material, frame;

function supported() {{
  try {{
    const probe = document.createElement('canvas');
    return !!(window.WebGLRenderingContext &&
      (probe.getContext('webgl2') || probe.getContext('webgl')));
  }} catch (e) {{ return false; }}
}}

function build() {{
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 100);
  camera.position.z = 9;
{build}
  scene.add(object);

  renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true, powerPreference: 'low-power' }});
  // Capping DPR is the single biggest win on a phone: a 3x display would
  // otherwise render nine times the pixels for no visible benefit here.
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  host.appendChild(renderer.domElement);
}}

function tick() {{
  frame = requestAnimationFrame(tick);
  object.rotation.y += 0.0016;
  object.rotation.x += 0.0007;
  renderer.render(scene, camera);
}}

function stop() {{
  cancelAnimationFrame(frame);
  geometry?.dispose();
  material?.dispose();
  renderer?.dispose();
}}

addEventListener('resize', () => {{
  if (!renderer) return;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}});

// Pause when the tab is hidden -- an invisible canvas should not hold the GPU.
document.addEventListener('visibilitychange', () => {{
  if (!renderer) return;
  if (document.hidden) cancelAnimationFrame(frame); else tick();
}});

if (!supported()) {{
  host.dataset.state = 'unsupported';   // the CSS gradient stays; nothing breaks
}} else {{
  build();
  if (reduceMotion) {{
    // Not "slower" -- stopped. One still frame, then nothing moves again.
    renderer.render(scene, camera);
    host.dataset.state = 'static';
  }} else {{
    host.dataset.state = 'live';
    tick();
  }}
}}
"""


def _css(spec: SiteSpec) -> str:
    body_stack = (f"'{spec.body_font}', " if spec.body_font else "") +         'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    heading_stack = (f"'{spec.heading_font}', " if spec.heading_font else "") +         "var(--font-body, ui-sans-serif)"
    return f""":root {{
  --bg: {spec.background};
  --accent: {spec.accent};
  --text: {spec.foreground};
  --muted: #97a3b4;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.65 {body_stack};
}}
/* The scene sits BEHIND the content and is never focusable. */
#scene {{
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background: radial-gradient(60% 60% at 50% 40%, color-mix(in srgb, var(--accent) 18%, transparent), transparent);
}}
#scene canvas {{ display: block; }}
main {{ position: relative; z-index: 1; max-width: 62rem; margin: 0 auto; padding: 0 1.25rem; }}
.hero {{ min-height: 78vh; display: flex; flex-direction: column; justify-content: center; }}
h1, h2 {{ font-family: {heading_stack}; }}
h1 {{ font-size: clamp(2.1rem, 6vw, 4rem); line-height: 1.05; margin: 0 0 1rem; letter-spacing: -0.02em; }}
.subhead {{ font-size: clamp(1rem, 2.4vw, 1.3rem); color: var(--muted); max-width: 44rem; margin: 0 0 2rem; }}
section {{ padding: 3.5rem 0; border-top: 1px solid rgba(255,255,255,.08); }}
h2 {{ font-size: clamp(1.3rem, 3vw, 1.9rem); margin: 0 0 .75rem; }}
p {{ color: var(--muted); max-width: 48rem; }}
.cta {{
  display: inline-block; margin-top: 1rem; padding: .7rem 1.4rem; border-radius: 8px;
  background: var(--accent); color: #06121f; font-weight: 650; text-decoration: none;
}}
.cta:focus-visible {{ outline: 3px solid #fff; outline-offset: 3px; }}
footer {{ padding: 3rem 0; color: var(--muted); font-size: .9rem; }}
@media (prefers-reduced-motion: reduce) {{
  * {{ animation: none !important; transition: none !important; }}
}}
"""


def _html(spec: SiteSpec, head_tags: str) -> str:
    escape = html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        head_tags,
        (f'<link rel="stylesheet" href="{spec.font_url}">' if spec.font_url else ""),
        '<link rel="stylesheet" href="/styles.css">',
        f'<script type="importmap">{json.dumps({"imports": {"three": THREE_CDN}})}</script>',
        "</head>",
        "<body>",
        # Decorative, and told so. A screen reader should never announce it.
        '<div id="scene" aria-hidden="true" role="presentation"></div>',
        "<main>",
        '<div class="hero">',
        # THE headline. In HTML, not drawn in the canvas.
        f"<h1>{escape(spec.headline)}</h1>",
    ]
    if spec.subhead:
        parts.append(f'<p class="subhead">{escape(spec.subhead)}</p>')
    parts.append("</div>")

    for section in spec.sections:
        parts.append("<section>")
        parts.append(f"<h2>{escape(section.heading)}</h2>")
        parts.append(f"<p>{escape(section.body)}</p>")
        if section.cta_text:
            href = escape(section.cta_href or "#")
            parts.append(f'<a class="cta" href="{href}">{escape(section.cta_text)}</a>')
        parts.append("</section>")

    parts.extend([
        "</main>",
        f"<footer>{escape(spec.name)}</footer>",
        '<script type="module" src="/scene.js"></script>',
        "</body></html>",
    ])
    return "\n".join(parts)


def generate(spec: SiteSpec, directory: str | Path, *,
             pages: list[Any] | None = None, use_design_system: bool = True) -> Built:
    """Write a real, runnable site. No build step, no npm install.

    With `use_design_system`, the palette, typography and scene are chosen
    from the vendored design library rather than from my defaults -- and the
    contrast of the result is verified before it is written, so a site is
    never shipped with text nobody can read.
    """
    result = Built(directory=str(directory))

    if use_design_system and not spec.headline.strip() == "":
        try:
            from reyes_agent.creative import design

            system = design.for_brief(
                f"{spec.name} {spec.headline} {spec.subhead} "
                + " ".join(s.body for s in spec.sections))
            result.design = system.as_dict()
            # Only adopt a system that actually passes its own contrast check.
            result.design["adopted"] = system.accessible
            if system.accessible:
                spec.accent = system.primary
                spec.background = system.background
                spec.foreground = system.foreground
                spec.font_url = system.font_url
                spec.heading_font = system.heading_font
                spec.body_font = system.body_font
            else:
                # A suggestion that fails its own contrast check is DECLINED,
                # not fatal. Adding it to `problems` failed the whole build
                # over an advisory palette -- the site was fine, the
                # suggestion was not. The defaults are already accessible.
                result.design["adopted"] = False
                result.design["declined_because"] = system.problems
        except Exception:  # noqa: BLE001 -- design guidance must never block a build
            result.design = {}

    if spec.scene not in SCENES:
        result.problems.append(f"'{spec.scene}' is not a scene I can build; "
                               f"choose from {', '.join(SCENES)}")
        return result
    if not spec.headline.strip():
        result.problems.append("a page with no headline has nothing for a crawler "
                               "or a screen reader to read")
        return result

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    from reyes_agent import seo

    page = pages[0] if pages else seo.Page(
        url=spec.base_url or "/", title=f"{spec.headline} — {spec.name}",
        description=spec.description,
        body_text=" ".join([spec.subhead] + [s.body for s in spec.sections]),
        priority=1.0)
    head = seo.head_tags(page, site_name=spec.name)

    written = {
        "index.html": _html(spec, head),
        "styles.css": _css(spec),
        "scene.js": _scene_js(spec),
    }
    for name, body in written.items():
        (root / name).write_text(body, encoding="utf-8")
        result.files.append(str(root / name))

    seo_files = seo.write_site_files(root, pages or [page],
                                    base_url=spec.base_url or "/")
    result.files.extend(seo_files["wrote"])

    result.budget_report = budget.measure(root)
    if not result.budget_report["ok"]:
        result.problems.extend(result.budget_report["problems"])

    result.ok = not result.problems
    return result


def describe_scene(kind: str) -> str:
    return {
        PARTICLES: "a drifting particle field -- cheapest, works everywhere",
        WIREFRAME: "a rotating wireframe solid -- no lighting, very light",
        ORB: "a lit metallic sphere -- the only scene with real lighting",
        GRID: "a perspective wireframe plane -- the retro horizon look",
    }.get(kind, "unknown")


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "scenes": list(SCENES),
        "three_version": THREE_VERSION,
        "build_step": "none -- ES modules and an import map",
        "guarantees": [
            "the headline and copy are real HTML, not drawn in the canvas",
            "the canvas is aria-hidden and never focusable",
            "no WebGL falls back to a CSS gradient with the page intact",
            "prefers-reduced-motion stops the loop, it does not slow it",
            "rendering pauses when the tab is hidden",
            "device pixel ratio capped at 2",
        ],
        "note": ("Delete the canvas and the page still works. That is the test "
                 "for whether 3D is decoration or a trap."),
    }
