"""Design-specific policy and evidence vocabulary for ZENO's existing brain.

No renderer, worker pool, or image model lives here.  Creation uses the
existing project/image tools; visual inspection uses the existing vision tool.
This module keeps the decision process compact, original, and honest.
"""

from __future__ import annotations

import re


CAPABILITY_LIBRARY = {
    "GRAPHIC_DESIGN": "AVAILABLE — direction, critique and real image/text/SVG assets through existing tools.",
    "LOGO_DESIGN": "PARTIAL — original discovery and vector/text masters; no native Illustrator/Figma control claimed.",
    "BRANDING": "AVAILABLE — positioning, identity direction and connected creator projects.",
    "BRAND_IDENTITY": "AVAILABLE — legacy capability name for connected positioning and identity direction.",
    "TYPOGRAPHY": "AVAILABLE — hierarchy, readability, pairing and spacing guidance.",
    "COLOUR_THEORY": "AVAILABLE — contrast, palette and accessibility guidance.",
    "LAYOUT": "AVAILABLE — hierarchy, grids, whitespace and composition guidance.",
    "UI_UX": "AVAILABLE — flows, wireframes, accessibility and project implementation guidance.",
    "WEB_DESIGN": "AVAILABLE — existing build/project tools can create and verify web assets.",
    "VIDEO_EDITING": "PARTIAL — creative direction and editing plans; no native timeline-editor automation claimed.",
    "MOTION_DESIGN": "PARTIAL — storyboard/motion direction; no permanent rendering engine.",
    "ANIMATION": "PARTIAL — lightweight web/CSS animation and concepts through existing project tools.",
    "3D_DESIGN": "PARTIAL — existing Blender path when installed/configured; availability is checked at execution.",
    "PHOTOGRAPHY": "AVAILABLE — composition, shot-list and image critique guidance.",
    "PHOTO_EDITING": "PARTIAL — image generation/vision critique, not verified pixel-editor automation.",
    "ILLUSTRATION": "PARTIAL — original concepts and image tooling where connected.",
    "SOCIAL_MEDIA_DESIGN": "AVAILABLE — formats, hierarchy and campaign creative direction.",
    "CONTENT_CREATION": "AVAILABLE — briefs, copy and content plans through the existing agent.",
    "COPYWRITING": "AVAILABLE — existing writing pipeline with owner review.",
    "PRESENTATION_DESIGN": "PARTIAL — narrative/layout direction; export capability depends on installed tools.",
    "PRINT_DESIGN": "PARTIAL — preflight guidance; printer-specific export must be verified.",
    "PACKAGING": "PARTIAL — concept, dieline-aware direction and mockup planning.",
    "PRODUCT_DESIGN": "AVAILABLE — discovery, audience and concept planning.",
    "AUDIO_EDITING": "PARTIAL — voice/audio tooling exists; no native DAW control claimed.",
    "MUSIC_PRODUCTION_BASICS": "AVAILABLE — educational guidance, not a claim of music mastering.",
    "GAME_DESIGN": "AVAILABLE — existing game/design specialist routing when needed.",
    "PROGRAMMING": "AVAILABLE — existing coding specialist and build tools.",
    "AI_TOOLS": "AVAILABLE — existing tool/model routing knowledge and research path.",
    "MARKETING": "AVAILABLE — planning through the existing business/research specialists.",
    "BUSINESS_DEVELOPMENT": "AVAILABLE — positioning and launch planning through existing specialists.",
}
CAPABILITIES = tuple(CAPABILITY_LIBRARY)

_DESIGN = re.compile(
    r"\b(graphic design|logo|brand(?:ing| identity)?|typography|kerning|colour|color|layout|"
    r"composition|flyer|poster|banner|business card|thumbnail|ui\s*/?\s*ux|wireframe|"
    r"design system|svg|vector|mockup|packaging|social media design|creative direction)\b", re.I)
_CRITIQUE = re.compile(r"\b(rate|critique|review|why does .* look|look amateur|look bad|more professional)\b", re.I)
_LOGO = re.compile(r"\b(logo|wordmark|lettermark|monogram|emblem|brand identity)\b", re.I)
_PRINT = re.compile(r"\b(print|bleed|cmyk|trim|safe area|dpi|ppi)\b", re.I)


def is_design_request(message: str) -> bool:
    return bool(_DESIGN.search(str(message or "")))


def directive(message: str) -> str:
    """Return a short policy nudge only for an actual design request."""
    text = str(message or "")
    if not is_design_request(text):
        return ""
    if _CRITIQUE.search(text):
        return (
            "[Design critique: base every observation on visual evidence actually available. Assess hierarchy, spacing, "
            "alignment, typography, colour/contrast, readability, composition, consistency and audience fit. Give the "
            "three highest-impact corrections. Scores are subjective diagnostics, never scientific facts. If no visual "
            "is available, say so and request a screenshot/upload rather than pretending you inspected it.]"
        )
    if _LOGO.search(text):
        return (
            "[Design direction: make original work, never imitate a named company's mark. For a serious logo, first obtain "
            "business, audience, personality and use context if missing; then offer at most three materially different "
            "directions. Test the chosen mark in monochrome and at small size. Prefer an SVG/vector master when an actual "
            "project-writing tool is used; never claim an asset was made unless its tool result confirms it.]"
        )
    if _PRINT.search(text):
        return (
            "[Print design: check final size, bleed, trim, safe area, resolution and CMYK/export constraints before calling "
            "a file print-ready. State any missing printer specification plainly.]"
        )
    return (
        "[Design direction: explain the principle and why it matters, then make concrete recommendations. For creation, use "
        "the existing image/project tools only when they can produce a real saved result; keep platform dimensions, hierarchy, "
        "contrast, accessibility and file format appropriate to the stated medium.]"
    )


def critique_prompt() -> str:
    """Question supplied to the existing screenshot + multimodal vision seam."""
    return (
        "Critique the visible design only. State observable evidence before conclusions. Assess visual hierarchy, spacing, "
        "alignment, typography, colour contrast, readability, composition, consistency and audience fit. Offer the three "
        "highest-impact corrections. If the screen does not show a design clearly, say that rather than guessing. Optional "
        "scores out of 10 are subjective diagnostic estimates, not measurements."
    )
