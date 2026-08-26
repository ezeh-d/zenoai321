"""Mode profiles: targets and constraints, never canned reply text."""

from __future__ import annotations

from reyes_agent.charm.models import CharmMode, StyleProfile


def _profile(
    mode: CharmMode,
    guidance: str,
    *,
    warmth: int,
    humor: int,
    flirt: int,
    directness: int,
    constraints: tuple[str, ...] = (),
) -> StyleProfile:
    return StyleProfile(mode, guidance, warmth, humor, flirt, directness, constraints)


_STYLES: dict[CharmMode, StyleProfile] = {
    CharmMode.NATURAL: _profile(CharmMode.NATURAL, "Sound effortless, specific to the exchange, and like the owner's normal voice.", warmth=60, humor=30, flirt=25, directness=60),
    CharmMode.SMOOTH: _profile(CharmMode.SMOOTH, "Use calm confidence, clean rhythm, and understated interest without forcing cleverness.", warmth=62, humor=35, flirt=55, directness=65),
    CharmMode.SWEET: _profile(CharmMode.SWEET, "Be kind, sincere, attentive, and gently affectionate without overpromising intimacy.", warmth=88, humor=20, flirt=38, directness=48),
    CharmMode.FLIRTY: _profile(CharmMode.FLIRTY, "Show mutual-interest-aware attraction with light confidence and no sexual pressure.", warmth=68, humor=45, flirt=78, directness=62, constraints=("Respect weak or negative reciprocity.",)),
    CharmMode.PLAYFUL: _profile(CharmMode.PLAYFUL, "Use light teasing, curiosity, and an easy conversational bounce.", warmth=66, humor=68, flirt=52, directness=52),
    CharmMode.FUNNY: _profile(CharmMode.FUNNY, "Find situational humor in the actual context; keep the joke brief and non-mean.", warmth=58, humor=90, flirt=35, directness=48),
    CharmMode.WITTY: _profile(CharmMode.WITTY, "Use concise observation and wordplay grounded in the conversation, not performance for its own sake.", warmth=52, humor=78, flirt=42, directness=66),
    CharmMode.ROMANTIC: _profile(CharmMode.ROMANTIC, "Express sincere affection proportionate to the established relationship and evidence of mutual interest.", warmth=94, humor=15, flirt=72, directness=54, constraints=("Do not manufacture closeness.",)),
    CharmMode.CONFIDENT: _profile(CharmMode.CONFIDENT, "Be self-assured, concise, and clear without dominance, entitlement, or bravado.", warmth=54, humor=28, flirt=46, directness=88),
    CharmMode.GENTLEMAN: _profile(CharmMode.GENTLEMAN, "Be respectful, composed, considerate, and clear about interest without pressure.", warmth=78, humor=24, flirt=42, directness=66),
    CharmMode.CHEEKY: _profile(CharmMode.CHEEKY, "Use a mischievous but warm edge; tease only where the context shows it will land well.", warmth=58, humor=76, flirt=64, directness=62),
    CharmMode.DEEP: _profile(CharmMode.DEEP, "Invite meaningful conversation with emotional honesty and a specific thoughtful observation.", warmth=76, humor=12, flirt=30, directness=58),
    CharmMode.SERIOUS: _profile(CharmMode.SERIOUS, "Be direct, grounded, emotionally responsible, and free of decorative banter.", warmth=46, humor=5, flirt=8, directness=92),
    CharmMode.PIDGIN_SMOOTH: _profile(CharmMode.PIDGIN_SMOOTH, "Use natural Nigerian Pidgin code-switching only where it fits the owner's voice; stay effortless and respectful.", warmth=68, humor=52, flirt=56, directness=62, constraints=("Do not caricature or overstuff Pidgin markers.",)),
}


def get_style(mode: CharmMode | str) -> StyleProfile:
    return _STYLES[CharmMode.parse(mode)]


def list_styles() -> tuple[str, ...]:
    return tuple(profile.mode.value for profile in _STYLES.values())
