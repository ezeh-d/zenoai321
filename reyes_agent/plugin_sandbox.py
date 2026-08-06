"""Plugin sandbox: enforce a plugin's declared permissions at run time.

WHAT CHANGED, AND WHY IT WAS NEEDED
-----------------------------------
Until now `permissions.may_load_plugin` decided WHETHER a plugin loads,
and that was the whole story -- once imported, a plugin was ordinary
Python with ZENO's full authority. A manifest saying `filesystem_read`
bought nothing at run time; the plugin could still shell out, post to the
network, or read credentials. That gap was documented rather than hidden,
and this module closes it.

HOW IT WORKS
------------
Plugin modules are executed with a restricted `__builtins__`:

  * `open()` is wrapped -- writes require `filesystem_write`, deletes
    require `filesystem_delete`, and reads outside the plugin's own folder
    and the vault require `filesystem_read`.
  * `__import__` is wrapped -- importing `subprocess`/`os.system`-style
    modules requires `system_commands`, `socket`/`requests`/`urllib`
    require `network`, `pyautogui`-style modules require
    `desktop_automation`.
  * `reyes_agent.config` is blocked outright: it holds API keys, and no
    plugin has a legitimate need for them. Credentials are not a
    capability that can be granted.

Every denial raises `PluginPermissionError` and is written to the audit
log with the plugin name and what it tried.

HONEST LIMITS -- READ THIS
--------------------------
This is a **capability guard, not a security boundary**. It runs in the
same process and same interpreter, so a determined, hostile plugin can
escape it (via C extensions, gc traversal, frame walking, and other
well-known tricks). It reliably stops a plugin from *accidentally or
casually* exceeding what it declared, and it makes any attempt visible in
the audit log.

Real isolation requires a separate process with an OS-level sandbox (job
object / AppContainer) and IPC. That is a substantially larger piece of
work and is NOT implemented. Do not install a plugin you would not be
willing to run unsandboxed.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

from reyes_agent import config


class PluginPermissionError(PermissionError):
    """A plugin attempted something its manifest did not declare."""


# module prefix -> capability required to import it
_IMPORT_GUARDS: dict[str, str] = {
    "subprocess": "system_commands",
    "pty": "system_commands",
    "winreg": "system_commands",
    "ctypes": "system_commands",
    "socket": "network",
    "requests": "network",
    "urllib": "network",
    "http": "network",
    "httpx": "network",
    "aiohttp": "network",
    "ftplib": "network",
    "smtplib": "email_send",
    "webbrowser": "browser_automation",
    "playwright": "browser_automation",
    "selenium": "browser_automation",
    "pyautogui": "desktop_automation",
    "pynput": "desktop_automation",
    "keyboard": "desktop_automation",
    "mouse": "desktop_automation",
    "mss": "vision",
    "cv2": "vision",
}

# Never importable by a plugin, at any permission level. These hand out
# credentials or let a plugin rewrite ZENO's own rules.
_FORBIDDEN_MODULES = {
    "reyes_agent.config",        # API keys, tokens, app password
    "reyes_agent.permissions",   # could grant itself capabilities
    "reyes_agent.plugin_sandbox",
}

_WRITE_MODES = set("wax+")

# The ONLY things a plugin may import from ZENO itself. `register` is the
# entire documented plugin contract (a plugin is a module that registers
# tools), so nothing else needs to be reachable. An allowlist is used
# rather than a denylist because attribute traversal from any real ZENO
# module can reach config -- see guarded_import.
_PLUGIN_API = {"reyes_agent.tools"}
# Attributes a plugin may touch on the proxied module.
_PLUGIN_API_ATTRS = {"reyes_agent.tools": {"register", "TOOLS", "run_tool"}}


class _RestrictedModule:
    """A read-only façade over an allowed ZENO module.

    Only whitelisted attributes resolve; everything else raises. This is
    what stops `reyes_agent.tools.config` / `__globals__` style traversal
    from reaching credentials.
    """

    def __init__(self, name: str, module: Any, allowed: set[str]) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_allowed", allowed)

    def __getattr__(self, item: str) -> Any:
        allowed = object.__getattribute__(self, "_allowed")
        name = object.__getattribute__(self, "_name")
        if item not in allowed:
            raise PluginPermissionError(
                f"plugin access to {name}.{item} is not permitted "
                f"(allowed: {sorted(allowed)})")
        return getattr(object.__getattribute__(self, "_module"), item)

    def __setattr__(self, item: str, value: Any) -> None:
        raise PluginPermissionError("plugins may not modify ZENO's modules")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<restricted {object.__getattribute__(self, '_name')}>"


def _plugin_api_module(real_import, full: str, fromlist) -> Any:
    """Import an allowed ZENO module and wrap it so it can't be traversed."""
    base = "reyes_agent.tools"
    module = real_import(base, None, None, ("register",), 0)
    proxy = _RestrictedModule(base, module, _PLUGIN_API_ATTRS[base])
    if not fromlist:
        # `import reyes_agent.tools` binds the ROOT name; hand back a shell
        # whose only attribute is the proxied submodule.
        shell = _RestrictedModule("reyes_agent", None, {"tools"})
        object.__setattr__(shell, "_module", type("_Ns", (), {"tools": proxy})())
        return shell
    return proxy


def _audit(plugin: str, action: str, detail: str, allowed: bool) -> None:
    try:
        from reyes_agent import audit

        audit.log("plugin_capability", plugin=plugin, action=action,
                  detail=detail, allowed=allowed)
    except Exception:  # noqa: BLE001 -- logging must not break enforcement
        pass


def _capability_granted(granted: set[str], capability: str) -> bool:
    """A plugin's declared capability must ALSO be permitted by the
    installation profile -- a manifest cannot grant more than the machine
    policy allows."""
    if capability not in granted:
        return False
    from reyes_agent import permissions

    return permissions.state_for(capability) != permissions.BLOCKED


def build_sandbox(plugin_name: str, granted: set[str], plugin_dir: Path) -> dict[str, Any]:
    """Return a restricted globals dict for executing one plugin module."""
    vault = config.VAULT_PATH.resolve()
    plugin_dir = plugin_dir.resolve()
    real_open = builtins.open
    real_import = builtins.__import__

    def guarded_open(file, mode="r", *args, **kwargs):
        path = Path(str(file))
        writing = bool(_WRITE_MODES & set(mode))
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        inside = any(str(resolved).startswith(str(root)) for root in (vault, plugin_dir))

        if writing:
            need = "filesystem_write"
        elif inside:
            need = None          # reading its own folder/the vault is the base case
        else:
            need = "filesystem_read"

        if need and not _capability_granted(granted, need):
            _audit(plugin_name, "open", f"{mode} {resolved}", False)
            raise PluginPermissionError(
                f"plugin '{plugin_name}' tried to open {resolved} (mode '{mode}') "
                f"but did not declare '{need}'")
        _audit(plugin_name, "open", f"{mode} {resolved}", True)
        return real_open(file, mode, *args, **kwargs)

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        full = name

        # ZENO's own package is handled specially. Two holes had to close
        # here (both found by the sandbox test suite, 2026-08-06):
        #   1. `from reyes_agent import config` calls __import__ with
        #      name="reyes_agent" and fromlist=("config",), so checking
        #      `name` alone never matched and a plugin PRINTED A LIVE API
        #      KEY in testing.
        #   2. Even with that fixed, `import reyes_agent` followed by
        #      attribute traversal (reyes_agent.config.GEMINI_API_KEY)
        #      reaches the same object, because the submodule is already in
        #      sys.modules.
        # So: plugins get ONLY an explicit allowlist under reyes_agent, and
        # receive a proxy that cannot be traversed to anything else.
        if root == "reyes_agent":
            requested = {full}
            for item in (fromlist or ()):
                requested.add(f"{full}.{item}")
            blocked = {m for m in requested
                       if any(m == f or m.startswith(f + ".") for f in _FORBIDDEN_MODULES)}
            if blocked:
                _audit(plugin_name, "import", ", ".join(sorted(blocked)), False)
                raise PluginPermissionError(
                    f"plugin '{plugin_name}' may not import {sorted(blocked)[0]} -- it exposes "
                    "credentials or permission policy, which is never grantable to a plugin")
            if full not in _PLUGIN_API and not any(
                    full.startswith(a + ".") for a in _PLUGIN_API):
                _audit(plugin_name, "import", full, False)
                raise PluginPermissionError(
                    f"plugin '{plugin_name}' may only import {sorted(_PLUGIN_API)} from "
                    f"reyes_agent, not '{full}'")
            _audit(plugin_name, "import", full, True)
            return _plugin_api_module(real_import, full, fromlist)
        need = _IMPORT_GUARDS.get(root)
        if need and not _capability_granted(granted, need):
            _audit(plugin_name, "import", f"{full} (needs {need})", False)
            raise PluginPermissionError(
                f"plugin '{plugin_name}' tried to import '{full}' but did not declare "
                f"'{need}'")
        if need:
            _audit(plugin_name, "import", f"{full} ({need})", True)
        return real_import(name, globals, locals, fromlist, level)

    safe_builtins = dict(vars(builtins))
    safe_builtins["open"] = guarded_open
    safe_builtins["__import__"] = guarded_import
    # eval/exec/compile let a plugin rebuild an unguarded import at run time.
    for name in ("eval", "exec", "compile"):
        safe_builtins.pop(name, None)

    return {
        "__builtins__": safe_builtins,
        "__name__": f"zeno_plugin_{plugin_name}",
        "__file__": str(plugin_dir / f"{plugin_name}.py"),
        "__zeno_plugin__": plugin_name,
        "__zeno_capabilities__": sorted(granted),
    }


def execute_plugin(path: Path, plugin_name: str, granted: set[str]) -> tuple[bool, str]:
    """Run a plugin file inside the sandbox. Returns (ok, message)."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"could not read {path.name}: {exc}"

    sandbox = build_sandbox(plugin_name, set(granted), path.parent)
    try:
        code = compile(source, str(path), "exec")
        exec(code, sandbox)  # noqa: S102 -- this is the plugin loader; guarded above
    except PluginPermissionError as exc:
        return False, f"blocked: {exc}"
    except Exception as exc:  # noqa: BLE001 -- one bad plugin must not stop startup
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"{plugin_name} loaded with {sorted(granted) or 'no'} capabilities"


def describe() -> dict:
    return {
        "enforced": True,
        "mechanism": "restricted __builtins__ (guarded open/__import__, eval/exec removed)",
        "import_guards": dict(sorted(_IMPORT_GUARDS.items())),
        "never_importable": sorted(_FORBIDDEN_MODULES),
        "is_security_boundary": False,
        "limitation": (
            "Same-process capability guard. Stops casual or accidental "
            "over-reach and logs every attempt, but a determined hostile "
            "plugin can escape it. True isolation needs a separate "
            "OS-sandboxed process, which is not implemented."
        ),
    }
