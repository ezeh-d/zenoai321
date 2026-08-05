"""Obsidian vault integration — REYES's second brain as editable markdown.

Point OBSIDIAN_VAULT_PATH in .env at your Obsidian vault folder. Every note REYES
saves becomes a real .md file you can open, edit, and see in Obsidian's graph.
Uses tags (frontmatter) and [[wiki links]] so the graph view works.

Safe by design: saving to an existing note APPENDS a dated block — it never
overwrites or deletes your existing writing.
"""
from __future__ import annotations

import os
import re
import time


def _slug(title: str) -> str:
    keep = re.sub(r"[^\w\s-]", "", title).strip()
    return re.sub(r"\s+", " ", keep) or "note"


class Obsidian:
    def _vault(self) -> str | None:
        from config import settings

        p = settings.obsidian_vault_path
        if not p:
            return None
        p = os.path.expanduser(p)
        os.makedirs(p, exist_ok=True)
        return p

    def obsidian_save(self, title: str, content: str, tags: str = "", links: str = "") -> str:
        vault = self._vault()
        if not vault:
            return "Obsidian not configured. Set OBSIDIAN_VAULT_PATH in .env to your vault folder."
        path = os.path.join(vault, f"{_slug(title)}.md")
        today = time.strftime("%Y-%m-%d %H:%M")

        link_line = ""
        if links:
            names = [f"[[{l.strip()}]]" for l in links.split(",") if l.strip()]
            link_line = "\nRelated: " + " ".join(names) + "\n"

        try:
            if os.path.exists(path):
                # append a dated block, never destroy existing content
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n## {today}\n{content}\n{link_line}")
                return f"Appended to existing note '{title}.md' in your vault."
            else:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                frontmatter = (
                    "---\n"
                    f"tags: [{', '.join(tag_list)}]\n"
                    f"created: {today}\n"
                    "---\n\n"
                )
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"{frontmatter}# {title}\n\n{content}\n{link_line}")
                return f"Created note '{title}.md' in your Obsidian vault."
        except Exception as e:  # noqa: BLE001
            return f"Error saving to vault: {e}"

    def obsidian_read(self, title: str) -> str:
        vault = self._vault()
        if not vault:
            return "Obsidian not configured. Set OBSIDIAN_VAULT_PATH in .env."
        path = os.path.join(vault, f"{_slug(title)}.md")
        if not os.path.exists(path):
            return f"No note titled '{title}' found."
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:6000]
        except Exception as e:  # noqa: BLE001
            return f"Error reading note: {e}"

    def obsidian_search(self, query: str, k: int = 10) -> str:
        vault = self._vault()
        if not vault:
            return "Obsidian not configured. Set OBSIDIAN_VAULT_PATH in .env."
        q = query.lower()
        hits: list[str] = []
        try:
            for dirpath, _dirs, files in os.walk(vault):
                for name in files:
                    if not name.endswith(".md"):
                        continue
                    full = os.path.join(dirpath, name)
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    if q in name.lower() or q in text.lower():
                        snippet = ""
                        for line in text.splitlines():
                            if q in line.lower():
                                snippet = line.strip()[:120]
                                break
                        hits.append(f"{name[:-3]}  —  {snippet}")
                        if len(hits) >= k:
                            break
            return "\n".join(hits) if hits else f"Nothing in your vault matches '{query}'."
        except Exception as e:  # noqa: BLE001
            return f"Error searching vault: {e}"

    def obsidian_list(self, limit: int = 30) -> str:
        vault = self._vault()
        if not vault:
            return "Obsidian not configured. Set OBSIDIAN_VAULT_PATH in .env."
        try:
            notes = []
            for dirpath, _dirs, files in os.walk(vault):
                for name in files:
                    if name.endswith(".md"):
                        full = os.path.join(dirpath, name)
                        notes.append((os.path.getmtime(full), name[:-3]))
            notes.sort(reverse=True)
            names = [n for _mt, n in notes[:limit]]
            return "\n".join(names) if names else "Your vault has no notes yet."
        except Exception as e:  # noqa: BLE001
            return f"Error listing vault: {e}"
