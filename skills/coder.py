"""Dedicated coder & website builder.

Scaffolds real, runnable starter projects, writes code files, and runs
build/dev/test commands (guarded). Higher-level than raw file writing:
one call gives you a working project skeleton you can run immediately.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable

_STATIC_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{name}</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header><h1>{name}</h1><p>Built by REYES.</p></header>
  <main id="app"></main>
  <script src="script.js"></script>
</body>
</html>
"""

_STATIC_CSS = """:root { --bg:#0b0f1a; --fg:#e6edf3; --accent:#4f9cff; }
* { box-sizing: border-box; }
body { margin:0; font-family:system-ui,sans-serif; background:var(--bg); color:var(--fg); }
header { padding:4rem 2rem; text-align:center; }
h1 { font-size:2.5rem; margin:0 0 .5rem; color:var(--accent); }
main { max-width:820px; margin:0 auto; padding:0 2rem 4rem; }
"""

_STATIC_JS = """document.getElementById('app').innerHTML =
  '<p>Edit script.js to build your site.</p>';
"""

_REACT_CDN = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{name}</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>body{{margin:0;font-family:system-ui,sans-serif;background:#0b0f1a;color:#e6edf3}}</style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    function App() {{
      const [n, setN] = React.useState(0);
      return <div style={{{{padding:'3rem',textAlign:'center'}}}}>
        <h1 style={{{{color:'#4f9cff'}}}}>{name}</h1>
        <button onClick={{() => setN(n + 1)}}>Clicked {{n}} times</button>
      </div>;
    }}
    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  </script>
</body>
</html>
"""

_FLASK_APP = """from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html", name="{name}")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
"""

_FLASK_INDEX = """<!doctype html>
<html><head><meta charset="utf-8"><title>{{{{ name }}}}</title></head>
<body><h1>{{{{ name }}}}</h1><p>Flask app built by REYES.</p></body></html>
"""

_FLASK_REQS = "flask>=3.0\n"

_PY_MAIN = '''"""{name} — a Python project scaffolded by REYES."""


def main():
    print("Hello from {name}!")


if __name__ == "__main__":
    main()
'''


class Coder:
    def __init__(self, approver: Callable[[str], bool], base_dir: str = "projects"):
        self.approver = approver
        self.base_dir = base_dir

    def _write(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def create_project(self, name: str, kind: str = "static-site") -> str:
        """kind: static-site | react | flask | python"""
        root = os.path.join(self.base_dir, name)
        os.makedirs(root, exist_ok=True)
        try:
            if kind == "static-site":
                self._write(os.path.join(root, "index.html"), _STATIC_HTML.format(name=name))
                self._write(os.path.join(root, "styles.css"), _STATIC_CSS)
                self._write(os.path.join(root, "script.js"), _STATIC_JS)
                how = f"Open {root}/index.html in a browser."
            elif kind == "react":
                self._write(os.path.join(root, "index.html"), _REACT_CDN.format(name=name))
                how = f"Open {root}/index.html in a browser (no build step needed)."
            elif kind == "flask":
                self._write(os.path.join(root, "app.py"), _FLASK_APP.format(name=name))
                self._write(os.path.join(root, "templates", "index.html"),
                            _FLASK_INDEX.format(name=name))
                self._write(os.path.join(root, "requirements.txt"), _FLASK_REQS)
                how = f"cd {root} && pip install -r requirements.txt && python app.py"
            elif kind == "python":
                self._write(os.path.join(root, "main.py"), _PY_MAIN.format(name=name))
                how = f"python {root}/main.py"
            else:
                return f"Unknown kind '{kind}'. Use: static-site, react, flask, python."
            return f"Created {kind} project at {root}.\nRun it: {how}"
        except Exception as e:  # noqa: BLE001
            return f"Error scaffolding project: {e}"

    def write_code(self, project: str, relpath: str, content: str) -> str:
        path = os.path.join(self.base_dir, project, relpath)
        if os.path.exists(path) and not self.approver(f"Overwrite {path}"):
            return "Cancelled by user."
        try:
            self._write(path, content)
            return f"Wrote {relpath} ({len(content)} chars)."
        except Exception as e:  # noqa: BLE001
            return f"Error writing {relpath}: {e}"

    def run(self, project: str, command: str) -> str:
        cwd = os.path.join(self.base_dir, project)
        if not self.approver(f"In {cwd}, run: {command}"):
            return "Cancelled by user."
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300
            )
            out = (result.stdout or "") + (result.stderr or "")
            return out.strip()[:5000] or "(no output)"
        except Exception as e:  # noqa: BLE001
            return f"Error running command: {e}"
