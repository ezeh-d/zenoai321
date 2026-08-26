"""ZENO migration CLI -- prepare the move to another laptop.

    python -m reyes_agent.migrate                 # inventory + checklist
    python -m reyes_agent.migrate export [path]    # write a secret-free bundle
    python -m reyes_agent.migrate import <zip>      # dry-run restore
    python -m reyes_agent.migrate import <zip> --apply
"""

from __future__ import annotations

import sys

from reyes_agent.migration import get_manager


def _print_preflight() -> None:
    mgr = get_manager()
    pf = mgr.preflight()
    try:
        from rich.box import ROUNDED
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text

        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        c = Console(legacy_windows=False)
        c.print(Text.assemble(("  ZENO MIGRATION  ", "bold cyan"),
                              (f"host {pf['hostname']}  ·  commit {pf['git_commit']}  ·  ", "grey62"),
                              (f"portable {pf['portable_size']}", "bold green")))
        style = {"portable": "green", "biometric": "yellow", "secret": "red", "rebuild": "grey62"}
        t = Table(box=ROUNDED, border_style="grey62")
        t.add_column("What"); t.add_column("Move?"); t.add_column("Size", justify="right"); t.add_column("Path", style="grey62")
        for r in pf["items"]:
            verb = {"portable": "EXPORT", "biometric": "opt-in", "secret": "BY HAND",
                    "rebuild": "rebuild"}[r["category"]]
            t.add_row(r["name"], Text(verb, style=style[r["category"]]),
                      r["size"] if r["exists"] else "-", r["path"])
        c.print(t)
        c.print(Text("\nChecklist:", style="bold cyan"))
        for step in pf["checklist"]:
            c.print("  " + step)
    except Exception:  # noqa: BLE001
        print(f"ZENO MIGRATION  host={pf['hostname']} commit={pf['git_commit']} portable={pf['portable_size']}")
        for r in pf["items"]:
            print(f"  [{r['category']:9}] {r['name']:22} {r['size'] if r['exists'] else '-':>8}  {r['path']}")
        print("\nChecklist:")
        for step in pf["checklist"]:
            print("  " + step)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "preflight"
    mgr = get_manager()
    if cmd in ("preflight", "inventory", "status"):
        _print_preflight()
        return 0
    if cmd == "export":
        dest = argv[1] if len(argv) > 1 else f"zeno-profile-{mgr.preflight()['hostname'] or 'export'}.zip"
        include_bio = "--include-biometrics" in argv
        res = mgr.export_profile(dest, include_biometrics=include_bio)
        if res.get("ok"):
            print(f"Exported {res['size']} -> {res['bundle']}")
            print("Included:", ", ".join(i["name"] for i in res["included"]) or "(nothing)")
            print("Excluded secrets (carry by hand):", ", ".join(res["excluded_secrets"]))
        else:
            print("Export failed:", res.get("error"))
            return 1
        return 0
    if cmd == "import":
        if len(argv) < 2:
            print("usage: python -m reyes_agent.migrate import <bundle.zip> [--apply]")
            return 2
        res = mgr.import_profile(argv[1], dry_run="--apply" not in argv)
        if not res.get("ok"):
            print("Import failed:", res.get("error"))
            return 1
        print(f"{'APPLIED' if not res['dry_run'] else 'DRY RUN'}: {res['files']} files")
        for p in res["planned"][:12]:
            print(f"  {p['from']} -> {p['to']}")
        print(res["note"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
