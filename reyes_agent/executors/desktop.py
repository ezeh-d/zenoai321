"""Desktop Executor -- where the owner's Desktop ACTUALLY is.

`%USERPROFILE%\\Desktop` is an assumption, not a fact. With OneDrive Folder
Backup (or any folder redirection) the real Desktop is
`%USERPROFILE%\\OneDrive\\Desktop`, and a project written to the assumed path
does not appear on the desktop the owner is looking at -- which reads
exactly like "ZENO said it saved it and it isn't there".

So the Windows Known Folder API (SHGetKnownFolderPath) is the source of
truth, with the naive path only as a last-resort fallback.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# FOLDERID_Desktop / FOLDERID_Documents / FOLDERID_Downloads
_FID_DESKTOP = (0xB4BFCC3A, 0xDB2C, 0x424C, (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))
_FID_DOCUMENTS = (0xFDD39AD0, 0x238F, 0x46AF, (0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
_FID_DOWNLOADS = (0x374DE290, 0x123F, 0x4565, (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))


def known_folder(guid: tuple, fallback: Path) -> Path:
    """Resolve one Known Folder, falling back to the naive path."""
    if sys.platform != "win32":
        return fallback
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        fid = _GUID(guid[0], guid[1], guid[2], (ctypes.c_ubyte * 8)(*guid[3]))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(out)) != 0:
            return fallback
        try:
            path = Path(out.value) if out.value else fallback
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
        return path if path.exists() else fallback
    except Exception:  # noqa: BLE001 -- resolution must never break a write
        return fallback


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def desktop_path() -> Path:
    """The owner's REAL Desktop, honouring OneDrive/redirection."""
    return known_folder(_FID_DESKTOP, _home() / "Desktop")


def documents_path() -> Path:
    return known_folder(_FID_DOCUMENTS, _home() / "Documents")


def downloads_path() -> Path:
    return known_folder(_FID_DOWNLOADS, _home() / "Downloads")


def website_workspace() -> Path:
    """Where generated websites live, isolated from ZENO's own code.

    Defaults to `Documents/ZENO Websites` (following the real Known Folder,
    so OneDrive redirection is honoured) and is overridable via
    WEBSITE_WORKSPACE_PATH. It must never resolve inside the ZENO
    installation: a generated project that can reach ZENO's source is the
    stability risk the Website Studio brief singles out.
    """
    from reyes_agent import config

    configured = getattr(config, "WEBSITE_WORKSPACE_PATH", None)
    root = Path(configured) if configured and str(configured).strip() else documents_path() / "ZENO Websites"
    root = root.expanduser()
    try:
        root.relative_to(Path(config.PROJECT_ROOT).resolve())
    except (ValueError, OSError):
        return root
    # Configured path points inside ZENO itself -- refuse it and fall back.
    return documents_path() / "ZENO Websites"


def describe() -> dict[str, str]:
    """Diagnostics: what was resolved, and whether redirection is in play."""
    desktop = desktop_path()
    naive = _home() / "Desktop"
    return {
        "desktop": str(desktop),
        "documents": str(documents_path()),
        "naive_desktop": str(naive),
        "redirected": str(desktop.resolve() != naive.resolve()).lower(),
        "exists": str(desktop.is_dir()).lower(),
    }


def resolve_destination(name: str) -> Path:
    """Turn what the owner said into a real, writable folder.

    Accepts the friendly names the Live Activity panel offers, plus any
    absolute path. Raises ValueError with a usable message otherwise --
    callers surface that rather than silently picking somewhere.
    """
    from reyes_agent import config

    label = " ".join(str(name or "").strip().casefold().replace("_", " ").replace("-", " ").split())
    if label in {"desktop", "my desktop", "the desktop"}:
        root = desktop_path()
    elif label in {"documents", "document", "my documents"}:
        root = documents_path()
    elif label in {"downloads", "download", "my downloads"}:
        root = downloads_path()
    elif label in {"zeno projects", "zeno project", "zeno"}:
        root = config.VAULT_PATH / "02-Projects"
    elif label in {"websites", "website", "website workspace", "zeno websites",
                   "website studio", "studio"}:
        root = website_workspace()
    else:
        raw = Path(str(name or "").strip()).expanduser()
        if not str(raw).strip():
            raise ValueError("Choose Desktop, Documents, ZENO Projects, or give a full folder path.")
        if not raw.is_absolute():
            raise ValueError(
                f"'{name}' is not a known location. Use Desktop, Documents, "
                "ZENO Projects, or a full folder path."
            )
        root = raw.resolve()
        if root == Path(root.anchor):
            raise ValueError("A drive root is not a valid project destination.")
    return root


def confirm_visible(project_dir: Path) -> tuple[bool, str]:
    """Confirm a finished project is actually on the Desktop the owner sees.

    Returns (on_desktop, human explanation). This is evidence for the final
    report, not decoration: it is how "saved to your Desktop" gets checked
    instead of assumed.
    """
    try:
        project_dir = Path(project_dir).resolve()
    except OSError as exc:
        return False, f"Could not resolve {project_dir}: {exc}"
    if not project_dir.is_dir():
        return False, f"{project_dir} does not exist."
    desktop = desktop_path().resolve()
    try:
        on_desktop = project_dir.parent.samefile(desktop)
    except OSError:
        on_desktop = project_dir.parent == desktop
    if not on_desktop:
        return False, f"{project_dir} exists, but its parent is not the Desktop ({desktop})."
    # Listing the Desktop is the actual proof the folder is visible there.
    try:
        visible = any(entry.name == project_dir.name for entry in desktop.iterdir())
    except OSError as exc:
        return False, f"Could not list the Desktop: {exc}"
    return (True, f"{project_dir.name} is visible on the Desktop at {project_dir}.") if visible else (
        False, f"{project_dir.name} was not found when listing {desktop}.")
