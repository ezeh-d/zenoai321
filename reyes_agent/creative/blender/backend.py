"""Blender driven by its Python API, not by clicking at it.

    "Do not rely entirely on mouse-coordinate automation. Prefer the Blender
     Python API, scripts, scene files, repeatable pipelines."

WHY SCRIPTING AND NOT THE GUI LADDER
------------------------------------
ZENO can operate GUIs, and for Blender it should not. A rendered frame
produced by clicking through menus is unreproducible: the same request next
week lands on a different layout, a different theme, a different add-on
state. `blender --background --python script.py` is deterministic, headless,
survives a version bump, and never fights the owner for the mouse.

VERIFIED ON THIS MACHINE
------------------------
Blender 5.2.0 LTS at `C:\\Program Files\\Blender Foundation\\Blender 5.2`.
It is NOT on PATH -- which is why `shutil.which` reported it missing and
why `inventory.find_application` exists.

RENDERING IS SLOW AND MUST NOT BLOCK ANYTHING
---------------------------------------------
A render is minutes, not milliseconds. Every call here takes a timeout, runs
headless in its own process, and returns a result that has been VERIFIED --
Blender exits 0 having written nothing often enough that the exit code is
not evidence.

SANDBOXING THE SCRIPT
---------------------
Generated Python runs inside Blender with full interpreter access, so the
script is written to a temp file ZENO controls, never assembled from
unvalidated input, and `render()` refuses a scene script containing imports
it has no reason to need.
"""

from __future__ import annotations

import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.capabilities import inventory
from reyes_agent.creative import verification

# A still frame is seconds; an animation is minutes. Both need a ceiling.
STILL_TIMEOUT_S = 300
ANIMATION_TIMEOUT_S = 1800

# Engine PREFERENCES, not enum values. Blender renamed EEVEE between
# versions -- 5.2 reports ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', 'CYCLES')
# while 4.2 used BLENDER_EEVEE_NEXT -- so the script resolves the real name
# at runtime from the enum the running build reports. Hardcoding it is how
# a render script rots on the next upgrade.
EEVEE = "eevee"
CYCLES = "cycles"
WORKBENCH = "workbench"

_ENGINE_PREFERENCES = {
    EEVEE: ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),
    CYCLES: ("CYCLES",),
    WORKBENCH: ("BLENDER_WORKBENCH",),
}

# Generated scene scripts have no business importing these.
_FORBIDDEN_IMPORTS = ("subprocess", "socket", "shutil", "requests", "urllib",
                      "ctypes", "importlib", "__import__")


@dataclass
class Result:
    ok: bool = False
    output: str = ""
    reason: str = ""
    seconds: float = 0.0
    stderr: str = ""
    media: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "reason": self.reason,
                "seconds": round(self.seconds, 1),
                "media": self.media.as_dict() if self.media else None}

    def summary(self) -> str:
        if not self.ok:
            return f"Blender did NOT produce a usable file: {self.reason}"
        detail = self.media.summary() if self.media else self.output
        return f"{detail} in {self.seconds:.0f}s"


def executable() -> str | None:
    """Blender, wherever it actually is. Not just PATH."""
    return inventory.find_application("blender")


def available() -> bool:
    return executable() is not None


def version() -> str:
    binary = executable()
    if not binary:
        return ""
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (result.stdout or "").strip().splitlines()[0] if result.stdout else ""
    except Exception:  # noqa: BLE001
        return ""


def _guard(script: str) -> str:
    """Refuse a generated scene script that reaches outside Blender."""
    lowered = script.lower()
    for banned in _FORBIDDEN_IMPORTS:
        if banned in lowered:
            return (f"the scene script references '{banned}', which a scene has no "
                    "reason to need")
    return ""


def run_script(script: str, *, timeout_s: int = STILL_TIMEOUT_S,
               blend_file: str | Path | None = None) -> Result:
    """Run Python inside headless Blender. The one execution path."""
    result = Result()
    binary = executable()
    if not binary:
        result.reason = ("Blender is not installed here. Install it from blender.org "
                         "-- I will not install software by myself.")
        return result

    refusal = _guard(script)
    if refusal:
        result.reason = refusal
        return result

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(script)
        script_path = handle.name

    args = [binary, "--background"]
    if blend_file:
        args.append(str(blend_file))
    args += ["--python", script_path, "--python-exit-code", "1"]

    started = time.time()
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result.seconds = time.time() - started
        result.output = (completed.stdout or "")[-4000:]
        result.stderr = (completed.stderr or "")[-4000:]

        # Blender exits 0 even when the --python script raised, so the exit
        # code alone is worthless. Observed directly: an AttributeError in
        # the scene script, a full traceback on stderr, and returncode 0.
        # The sentinel is printed only if the script reached the end.
        raised = "Traceback (most recent call last)" in result.stderr
        reached_end = "ZENO_BLENDER_DONE" in result.output
        result.ok = completed.returncode == 0 and reached_end and not raised

        if result.ok:
            result.reason = "script completed"
        elif raised:
            last = [l for l in result.stderr.strip().splitlines() if l.strip()]
            result.reason = ("the scene script raised: "
                             + (last[-1][:300] if last else "unknown error"))
        elif not reached_end:
            result.reason = ("the scene script did not run to completion "
                             f"(Blender exited {completed.returncode})")
        else:
            result.reason = (f"Blender exited {completed.returncode}: "
                             f"{result.stderr.strip()[:300] or 'no error text'}")
    except subprocess.TimeoutExpired:
        result.seconds = time.time() - started
        result.reason = f"Blender did not finish within {timeout_s}s"
    except Exception as exc:  # noqa: BLE001
        result.reason = f"{type(exc).__name__}: {exc}"
    finally:
        Path(script_path).unlink(missing_ok=True)
    return result


# --- scene building -----------------------------------------------------

def spinning_object_script(*, output: str, shape: str = "torus",
                           colour: tuple[float, float, float] = (0.30, 0.64, 1.0),
                           frames: int = 60, resolution: tuple[int, int] = (1080, 1920),
                           engine: str = EEVEE, samples: int = 24,
                           background: tuple[float, float, float] = (0.02, 0.03, 0.05),
                           animation: bool = True) -> str:
    """A lit, rotating object -- the 3D logo-intro shape, built procedurally.

    Procedural rather than an imported model on purpose: nothing to
    download, nothing to go missing, and the result is reproducible from
    the parameters alone.
    """
    shapes = {
        "torus": "bpy.ops.mesh.primitive_torus_add(major_radius=1.3, minor_radius=0.42)",
        "cube": "bpy.ops.mesh.primitive_cube_add(size=2)",
        "sphere": "bpy.ops.mesh.primitive_uv_sphere_add(radius=1.3)",
        "cone": "bpy.ops.mesh.primitive_cone_add(radius1=1.2, depth=2.2)",
        "monkey": "bpy.ops.mesh.primitive_monkey_add(size=2)",
    }
    primitive = shapes.get(shape, shapes["torus"])
    width, height = resolution
    out = str(output).replace("\\", "/")

    return textwrap.dedent(f"""
        import bpy, math

        # Start from nothing -- the default cube would end up in the render.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene

        {primitive}
        target = bpy.context.active_object
        target.name = "Subject"
        bpy.ops.object.shade_smooth()

        material = bpy.data.materials.new("SubjectMaterial")
        material.use_nodes = True
        bsdf = material.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = ({colour[0]}, {colour[1]}, {colour[2]}, 1)
        bsdf.inputs["Metallic"].default_value = 0.85
        bsdf.inputs["Roughness"].default_value = 0.22
        target.data.materials.append(material)

        world = bpy.data.worlds.new("World")
        scene.world = world
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (
            {background[0]}, {background[1]}, {background[2]}, 1)

        key = bpy.data.objects.new("Key", bpy.data.lights.new("KeyLight", type='AREA'))
        key.data.energy = 900
        key.data.size = 6
        key.location = (4.5, -4.5, 5.5)
        key.rotation_euler = (math.radians(52), 0, math.radians(44))
        scene.collection.objects.link(key)

        rim = bpy.data.objects.new("Rim", bpy.data.lights.new("RimLight", type='AREA'))
        rim.data.energy = 420
        rim.data.size = 5
        rim.location = (-4.5, 3.5, 2.5)
        rim.rotation_euler = (math.radians(72), 0, math.radians(-125))
        scene.collection.objects.link(rim)

        camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        camera.location = (0, -6.2, 1.4)
        camera.rotation_euler = (math.radians(82), 0, 0)
        scene.collection.objects.link(camera)
        scene.camera = camera

        # Set the interpolation default BEFORE keyframing rather than walking
        # fcurves afterwards. Blender 4.4+ moved to slotted actions, so
        # `action.fcurves` no longer exists -- and reaching for it made the
        # script raise while Blender still exited 0, writing nothing.
        try:
            bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
        except AttributeError:
            pass

        # Rotate the SUBJECT rather than the camera: one keyframed channel,
        # and the lighting stays put.
        target.rotation_euler = (0, 0, 0)
        target.keyframe_insert("rotation_euler", frame=1)
        target.rotation_euler = (0, 0, math.radians(360))
        target.keyframe_insert("rotation_euler", frame={frames})

        # Ask this Blender what its engines are actually called.
        wanted = {list(_ENGINE_PREFERENCES.get(engine, _ENGINE_PREFERENCES[EEVEE]))!r}
        available = [item.identifier for item in
                     bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
        scene.render.engine = next((name for name in wanted if name in available),
                                   available[0])
        print("ZENO_ENGINE=" + scene.render.engine)

        scene.render.resolution_x = {width}
        scene.render.resolution_y = {height}
        scene.render.resolution_percentage = 100
        scene.render.fps = 30
        scene.frame_start = 1
        scene.frame_end = {frames}
        try:
            scene.eevee.taa_render_samples = {samples}
        except AttributeError:
            scene.cycles.samples = {samples}

        # PNG frames, encoded by ffmpeg afterwards. Blender's FFMPEG output is
        # an OPTIONAL build feature -- this 5.2 build reports only still
        # formats -- and depending on it makes the pipeline fail on exactly
        # the machines that have Blender. Frames then ffmpeg is also the
        # normal professional route: better encoder control, and it survives
        # a crashed render because the completed frames are still there.
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        scene.render.filepath = r"{out}/frame_"

        bpy.ops.render.render(animation={bool(animation)}, write_still={not bool(animation)})
        print("ZENO_BLENDER_DONE")
    """).strip()


def render_spin(output: str | Path, *, shape: str = "torus", frames: int = 60,
                resolution: tuple[int, int] = (1080, 1920),
                colour: tuple[float, float, float] = (0.30, 0.64, 1.0),
                engine: str = EEVEE, samples: int = 24,
                timeout_s: int = ANIMATION_TIMEOUT_S) -> Result:
    """Render a spinning object to a real video, then verify it plays."""
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)

    frames_dir = Path(tempfile.mkdtemp(prefix="zeno_frames_"))
    script = spinning_object_script(output=frames_dir.as_posix(), shape=shape,
                                    frames=frames, resolution=resolution,
                                    colour=colour, engine=engine, samples=samples,
                                    animation=True)

    result = run_script(script, timeout_s=timeout_s)
    if not result.ok:
        return result

    rendered = sorted(frames_dir.glob("frame_*.png"))
    if not rendered:
        result.ok = False
        result.reason = ("Blender reported success but rendered no frames -- "
                         "the exit code is not evidence")
        return result
    if len(rendered) < frames:
        result.reason = (f"only {len(rendered)} of {frames} frames rendered; "
                         "encoding what exists")

    encoded, why = _encode(frames_dir, target, fps=30)
    if not encoded:
        result.ok = False
        result.reason = why
        return result

    result.output = str(target)
    result.media = verification.verify_render(
        target, min_duration_s=max(0.3, len(rendered) / 30 * 0.7),
        expect_aspect="9:16" if resolution[1] > resolution[0] else "16:9")
    result.ok = result.media.ok
    result.reason = result.media.reason if result.ok else result.media.reason
    return result


def _encode(frames_dir: Path, target: Path, *, fps: int = 30) -> tuple[bool, str]:
    """Frames -> H.264, with ffmpeg. The tool that is actually good at this."""
    binary = inventory.which("ffmpeg")
    if not binary:
        return False, ("Blender rendered the frames but ffmpeg is not installed to "
                       f"encode them. The frames are in {frames_dir}.")
    args = [binary, "-y", "-loglevel", "error", "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%04d.png"),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        return False, f"encoding failed: {type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        return False, f"ffmpeg could not encode the frames: {completed.stderr[-300:]}"
    return True, "encoded"


def status() -> dict[str, Any]:
    binary = executable()
    return {
        "state": "READY" if binary else "DEPENDENCY_MISSING",
        "executable": binary,
        "version": version() if binary else "",
        "on_path": bool(inventory.which("blender")),
        "engines": [EEVEE, CYCLES, WORKBENCH],
        "shapes": ["torus", "cube", "sphere", "cone", "monkey"],
        "control": "Python API, headless -- never GUI clicking",
        "note": ("Blender is usually NOT on PATH; it is found through the install "
                 "registry. A render is verified afterwards because Blender exits "
                 "0 having written nothing often enough that the exit code proves "
                 "nothing."),
    }
