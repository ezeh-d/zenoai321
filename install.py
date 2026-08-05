"""
REYES installer.

    python install.py            # install everything needed to run REYES
    python install.py --minimal  # just the terminal brain (fastest)
    python install.py --all      # everything + optional extras (wake word, OCR)
    python install.py --venv     # do it inside a fresh virtual environment

It installs in groups and keeps going if one package fails (e.g. PyAudio needs
system libs on some machines), then prints a summary so you know exactly what,
if anything, still needs attention. It also creates your .env and runs the
doctor at the end.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = sys.platform.startswith("win")

# name -> list of pip requirements
GROUPS: dict[str, list[str]] = {
    "core (terminal brain)": [
        "litellm>=1.40", "pydantic-settings>=2.0", "python-dotenv>=1.0",
        "requests>=2.31", "psutil>=5.9",
    ],
    "GUI HUD": ["PySide6>=6.6"],
    "voice": [
        "SpeechRecognition>=3.10", "PyAudio>=0.2.14", "pyttsx3>=2.90",
        "faster-whisper>=1.0", "onnxruntime>=1.17", "soundfile>=0.12",
    ],
    "automation": ["pyautogui>=0.9.54", "pyperclip>=1.8", "mss>=9.0"],
    "browser": ["playwright>=1.44"],
}

WINDOWS_ONLY = ["pycaw>=20240210", "comtypes>=1.4"]
EXTRAS = ["openwakeword>=0.6", "pytesseract", "opencv-python", "duckduckgo-search>=6.0"]

MINIMAL_ONLY = {"core (terminal brain)"}


def pip_install(pkgs: list[str]) -> bool:
    """Install a list of packages. Returns True on success."""
    if not pkgs:
        return True
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *pkgs]
    print("   $", " ".join(cmd[4:]))
    return subprocess.call(cmd) == 0


def ensure_pip() -> None:
    subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])


def make_venv() -> None:
    venv_dir = ROOT / ".venv"
    if venv_dir.exists():
        print(f".venv already exists at {venv_dir}")
    else:
        print("Creating virtual environment in .venv ...")
        subprocess.call([sys.executable, "-m", "venv", str(venv_dir)])
    py = venv_dir / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
    print("\nVirtual environment ready. Re-run the installer with it:")
    print(f"   {py}  install.py")
    print("Then activate it to run REYES:")
    if IS_WIN:
        print(r"   .venv\Scripts\activate")
    else:
        print("   source .venv/bin/activate")


def setup_env() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        print(".env already present — leaving it as is.")
    elif example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example — open it and add a model key, "
              "or use Ollama (free/offline).")
    else:
        print("No .env.example found; skipping .env creation.")


def main() -> None:
    args = set(sys.argv[1:])
    if "--venv" in args:
        make_venv()
        return

    minimal = "--minimal" in args
    do_all = "--all" in args

    print(f"REYES installer  ·  Python {sys.version_info.major}.{sys.version_info.minor}  "
          f"·  {sys.platform}\n")
    ensure_pip()

    results: dict[str, bool] = {}
    for name, pkgs in GROUPS.items():
        if minimal and name not in MINIMAL_ONLY:
            continue
        print(f"\n▶ installing {name} ...")
        results[name] = pip_install(pkgs)

    if IS_WIN and not minimal:
        print("\n▶ installing Windows audio extras ...")
        results["windows audio"] = pip_install(WINDOWS_ONLY)

    if do_all:
        print("\n▶ installing optional extras ...")
        results["extras"] = pip_install(EXTRAS)

    # playwright needs its browser downloaded
    if not minimal and results.get("browser"):
        print("\n▶ downloading the browser for web automation ...")
        subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])

    print("\n" + "=" * 48)
    print("Install summary:")
    for name, ok in results.items():
        print(f"   {'OK ' if ok else 'FAILED'}  {name}")
    if not all(results.values()):
        print("\nSome groups failed. Common cause: PyAudio needs system audio "
              "libraries.\n  - Windows: pip install pipwin && pipwin install pyaudio\n"
              "  - macOS:   brew install portaudio && pip install pyaudio\n"
              "  - Linux:   sudo apt install portaudio19-dev && pip install pyaudio")
    print("=" * 48 + "\n")

    setup_env()

    print("\nRunning the doctor to show what's ready ...\n")
    subprocess.call([sys.executable, str(ROOT / "doctor.py")])

    print("\nDone. Start REYES with:  python start.py")


if __name__ == "__main__":
    main()
