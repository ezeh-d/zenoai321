"""Turn a brief into a concrete design system -- and check it, not trust it.

WHAT THIS PRODUCES
------------------
Real values: a full token palette, a font pairing with its actual Google
Fonts URL, a named visual style, and CSS custom properties ready to drop
into a page. Chosen from 192 palettes, 74 pairings and 84 styles that human
designers actually settled on, rather than invented per request.

WHY IT RE-CHECKS THE CONTRAST
-----------------------------
The palette data is careful -- some rows even carry notes like "Accent
adjusted from #F97316 for WCAG 3:1". That is a good sign about the source
and still not a reason to skip the check. Contrast is arithmetic on two hex
values: ZENO can compute it in microseconds and know, rather than inherit
someone else's claim about a row it is about to put on a real page.

So every chosen pair is measured, and `problems` names any that fall below
the WCAG AA threshold. A design system that ships unreadable text because a
CSV said it was fine is exactly the kind of confident wrongness this
project keeps trying to design out.

THIS IS GUIDANCE MADE CONCRETE, NOT TASTE
-----------------------------------------
It picks a defensible starting point from real conventions. It does not
claim the result is beautiful, and `explain()` says which row was chosen
and why so the owner can overrule it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.creative.design import library

# WCAG 2.1 AA. 4.5:1 for body text, 3:1 for large text and UI boundaries.
AA_TEXT = 4.5
AA_LARGE = 3.0


def _hex_to_rgb(value: str) -> tuple[float, float, float] | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return None
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG relative luminance -- the linearisation matters, sRGB is gamma-encoded."""
    channels = [(c / 12.92) if c <= 0.03928 else (((c + 0.055) / 1.055) ** 2.4)
                for c in rgb]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(foreground: str, background: str) -> float:
    """Contrast ratio between two hex colours. 1.0 = identical, 21.0 = max."""
    front, back = _hex_to_rgb(foreground), _hex_to_rgb(background)
    if front is None or back is None:
        return 0.0
    light, dark = sorted((_luminance(front), _luminance(back)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@dataclass
class DesignSystem:
    brief: str = ""
    # palette
    primary: str = "#2563EB"
    on_primary: str = "#FFFFFF"
    accent: str = "#EA580C"
    background: str = "#F8FAFC"
    foreground: str = "#1E293B"
    card: str = "#FFFFFF"
    muted: str = "#64748B"
    palette_name: str = ""
    # typography
    heading_font: str = "Inter"
    body_font: str = "Inter"
    font_url: str = ""
    pairing_name: str = ""
    # style
    style_name: str = ""
    effects: str = ""
    dark_mode: bool = False
    # honesty
    chosen_because: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def accessible(self) -> bool:
        return not self.problems

    def css_variables(self) -> str:
        """Real custom properties, ready to paste into a stylesheet."""
        return "\n".join([
            ":root {",
            f"  --primary: {self.primary};",
            f"  --on-primary: {self.on_primary};",
            f"  --accent: {self.accent};",
            f"  --background: {self.background};",
            f"  --foreground: {self.foreground};",
            f"  --card: {self.card};",
            f"  --muted: {self.muted};",
            f"  --font-heading: '{self.heading_font}', ui-sans-serif, system-ui, sans-serif;",
            f"  --font-body: '{self.body_font}', ui-sans-serif, system-ui, sans-serif;",
            "}",
        ])

    def font_link(self) -> str:
        return (f'<link rel="stylesheet" href="{self.font_url}">'
                if self.font_url else "")

    def contrasts(self) -> dict[str, float]:
        return {
            "body text on background": contrast(self.foreground, self.background),
            "text on card": contrast(self.foreground, self.card),
            "label on primary": contrast(self.on_primary, self.primary),
            "muted on background": contrast(self.muted, self.background),
            "accent on background": contrast(self.accent, self.background),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "brief": self.brief,
            "palette": {"name": self.palette_name, "primary": self.primary,
                        "on_primary": self.on_primary, "accent": self.accent,
                        "background": self.background, "foreground": self.foreground,
                        "card": self.card, "muted": self.muted},
            "typography": {"pairing": self.pairing_name, "heading": self.heading_font,
                           "body": self.body_font, "url": self.font_url},
            "style": {"name": self.style_name, "effects": self.effects,
                      "dark_mode": self.dark_mode},
            "contrast": {k: round(v, 2) for k, v in self.contrasts().items()},
            "accessible": self.accessible,
            "problems": self.problems,
            "chosen_because": self.chosen_because,
        }

    def explain(self) -> str:
        lines = [f"Design system for: {self.brief}"]
        for what, why in self.chosen_because.items():
            lines.append(f"  {what}: {why}")
        for label, ratio in self.contrasts().items():
            mark = "ok " if ratio >= AA_TEXT else ("large-only" if ratio >= AA_LARGE
                                                   else "FAILS")
            lines.append(f"  contrast {label}: {ratio:.1f}:1 [{mark}]")
        for problem in self.problems:
            lines.append(f"  ! {problem}")
        return "\n".join(lines)


# The exact tables to draw from. `table="styles"` is a SUBSTRING match and
# also hits logo_styles, icon_styles and cip_styles -- different schemas
# with different columns, which produced a design system with an empty style
# name and a "Best For" borrowed from a photography table.
PALETTE_TABLE = "ui-ux-pro-max__colors"
TYPOGRAPHY_TABLE = "ui-ux-pro-max__typography"
STYLE_TABLE = "ui-ux-pro-max__styles"


def _search(brief: str, table: str, limit: int) -> list[library.Match]:
    """Search ONE named table, never a family of similarly-named ones."""
    return [m for m in library.search(brief, table=table, limit=limit * 3)
            if m.table == table][:limit]


def for_brief(brief: str, *, dark: bool | None = None) -> DesignSystem:
    """Pick a palette, a pairing and a style for this brief. Then verify."""
    system = DesignSystem(brief=str(brief or ""))

    wants_dark = (dark if dark is not None
                  else bool(re.search(r"\b(dark|night|cyber|neon|noir|hacker)\b",
                                      brief or "", re.I)))
    system.dark_mode = wants_dark

    # --- palette -------------------------------------------------------
    palettes = _search(brief, PALETTE_TABLE, 6)
    chosen = None
    for match in palettes:
        row = match.row
        background = row.get("Background", "")
        is_dark = _luminance(_hex_to_rgb(background) or (1, 1, 1)) < 0.2
        if is_dark == wants_dark:
            chosen = row
            break
    if chosen is None and palettes:
        chosen = palettes[0].row

    if chosen:
        system.palette_name = chosen.get("Product Type", "")
        system.primary = chosen.get("Primary", system.primary)
        system.on_primary = chosen.get("On Primary", system.on_primary)
        system.accent = chosen.get("Accent", system.accent)
        system.background = chosen.get("Background", system.background)
        system.foreground = chosen.get("Foreground", system.foreground)
        system.card = chosen.get("Card", system.card)
        system.muted = chosen.get("Muted Foreground") or chosen.get("Muted", system.muted)
        system.chosen_because["palette"] = (
            f"'{system.palette_name}' — closest match, "
            f"{'dark' if wants_dark else 'light'} background as the brief implies")

    # --- typography ----------------------------------------------------
    pairings = _search(brief, TYPOGRAPHY_TABLE, 4)
    if pairings:
        row = pairings[0].row
        system.pairing_name = row.get("Font Pairing Name", "")
        system.heading_font = row.get("Heading Font", system.heading_font)
        system.body_font = row.get("Body Font", system.body_font)
        system.font_url = row.get("Google Fonts URL", "")
        system.chosen_because["typography"] = (
            f"'{system.pairing_name}' ({row.get('Category', '')}) — "
            f"{(row.get('Mood/Style Keywords') or '')[:60]}")

    # --- style ---------------------------------------------------------
    styles = _search(brief, STYLE_TABLE, 4)
    for match in styles:
        row = match.row
        # Respect the data's own accessibility and mobile flags.
        if str(row.get("Mobile-Friendly", "")).strip().lower() in ("no", "false", "✗"):
            continue
        if not str(row.get("Style Category", "")).strip():
            continue          # an unnamed style is not a choice
        system.style_name = row.get("Style Category", "")
        system.effects = row.get("Effects & Animation", "")
        system.chosen_because["style"] = (
            f"'{system.style_name}' — {(row.get('Best For') or '')[:60]}")
        break

    _verify(system)
    return system


def _verify(system: DesignSystem) -> None:
    """Measure the contrast rather than trusting the row that supplied it."""
    checks = (
        ("body text", system.foreground, system.background, AA_TEXT),
        ("text on cards", system.foreground, system.card, AA_TEXT),
        ("label on primary", system.on_primary, system.primary, AA_TEXT),
        ("muted text", system.muted, system.background, AA_LARGE),
    )
    for label, front, back, threshold in checks:
        ratio = contrast(front, back)
        if ratio == 0.0:
            system.problems.append(f"{label}: could not read the colour values")
        elif ratio < threshold:
            system.problems.append(
                f"{label} is {ratio:.1f}:1 against its background, below the "
                f"{threshold}:1 WCAG AA threshold — it would be hard to read")


def status() -> dict[str, Any]:
    data = library.status()
    return {
        "state": data["state"],
        "palettes": len(library.rows("ui-ux-pro-max__colors")),
        "font_pairings": len(library.rows("ui-ux-pro-max__typography")),
        "styles": len(library.rows("ui-ux-pro-max__styles")),
        "verifies": "WCAG AA contrast on every chosen pair, computed not inherited",
        "thresholds": {"text": AA_TEXT, "large_text": AA_LARGE},
        "attribution": library.ATTRIBUTION,
        "note": ("Picks a defensible starting point from real conventions and says "
                 "which row it chose and why, so the owner can overrule it."),
    }
