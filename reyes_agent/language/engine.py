"""UniversalLanguageEngine -- the one entry point.

    raw input
      -> sanitise (unicode, invisible characters, injection scan)
      -> owner phrase memory
      -> detect language / script / code-switching
      -> FAST PATH: confident English leaves here in ~0.3ms
      -> protect (secrets, code, entities, numbers)
      -> normalise (Pidgin, slang, idiom, typos)
      -> translate (adapter router, local-first)
      -> restore protected values
      -> verify (negation, numbers, entities, imperative)
      -> Understanding

THE FAST PATH IS NOT AN OPTIMISATION, IT IS THE DESIGN
------------------------------------------------------
Most input to this assistant is already English. The capability router work
brought "what time is it" from 10.05s to ~1.1s, and a language layer that
added even 50ms to every turn would eat a measurable slice of that back. So
confident English exits after detection, having done nothing but a Unicode
scan.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not execute anything, and it does not decide anything is safe. It
returns an `Understanding` carrying English text and a confidence. The intent
parser, the capability system and the permission gates are unchanged and
still run afterwards -- a sentence arriving in Yoruba gets no more authority
than the same sentence in English.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.language import detect as _detect
from reyes_agent.language import memory as _memory
from reyes_agent.language import normalize as _normalize
from reyes_agent.language import protect as _protect
from reyes_agent.language import safety as _safety
from reyes_agent.language import translate as _translate
from reyes_agent.language import verify as _verify

# Below this, a privileged action must ask rather than assume.
SENSITIVE_THRESHOLD = 0.75
# Below this, even conversation should say it is unsure.
CLARIFY_THRESHOLD = 0.35


@dataclass
class Understanding:
    """Everything downstream needs, and nothing it should not have."""

    raw_text: str
    english: str
    language: str
    languages: tuple[str, ...] = ()
    script: str = ""
    code_switched: bool = False
    confidence: float = 1.0
    language_confidence: float = 1.0
    translation_confidence: float = 1.0
    semantic_confidence: float = 1.0
    engine: str = "fast-path"
    fast_path: bool = False
    latency_ms: float = 0.0
    issues: list[str] = field(default_factory=list)
    suspicious: bool = False
    injection_markers: tuple[str, ...] = ()
    entities: dict[str, str] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)

    @property
    def safe_for_sensitive_action(self) -> bool:
        """Whether a privileged action may run without asking first."""
        return self.confidence >= SENSITIVE_THRESHOLD and not self.issues

    @property
    def needs_clarification(self) -> bool:
        return self.confidence < CLARIFY_THRESHOLD

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "english_meaning": self.english,
            "detected_languages": list(self.languages) or [self.language],
            "language": self.language,
            "script": self.script,
            "code_switched": self.code_switched,
            "confidence": round(self.confidence, 3),
            "language_confidence": round(self.language_confidence, 3),
            "translation_confidence": round(self.translation_confidence, 3),
            "semantic_confidence": round(self.semantic_confidence, 3),
            "engine": self.engine,
            "fast_path": self.fast_path,
            "latency_ms": round(self.latency_ms, 2),
            "issues": self.issues,
            "suspicious": self.suspicious,
            "injection_markers": list(self.injection_markers),
            "entities": self.entities,
        }


def _enabled() -> bool:
    from reyes_agent import config

    return bool(getattr(config, "LANGUAGE_ENGINE_ENABLED", True))


def _local_only() -> bool:
    from reyes_agent import config

    policy = str(getattr(config, "LANGUAGE_PRIVACY", "LOCAL_PREFERRED")).upper()
    return policy == "LOCAL_ONLY"


def understand_text(text: str, *, conversation_context: str = "",
                    target_language: str = "en",
                    use_memory: bool = True) -> Understanding:
    """Turn any input into clear English plus an honest confidence."""
    started = time.perf_counter()
    raw = str(text or "")

    if not raw.strip():
        return Understanding(raw, raw, "unknown", confidence=1.0, fast_path=True,
                             latency_ms=(time.perf_counter() - started) * 1000)

    if not _enabled():
        return Understanding(raw, raw, "en", confidence=1.0, fast_path=True,
                             engine="disabled",
                             latency_ms=(time.perf_counter() - started) * 1000)

    # --- 1. Unicode and injection ----------------------------------------
    report = _safety.sanitise(raw)
    working = report.cleaned

    # --- 2. Owner vocabulary ---------------------------------------------
    applied_phrases: list[str] = []
    if use_memory:
        try:
            working, applied_phrases = _memory.get_memory().apply(working)
        except Exception:  # noqa: BLE001
            pass  # memory must never be able to break understanding

    # --- 3. Detection ------------------------------------------------------
    detection = _detect.detect(working)
    languages = tuple(dict.fromkeys(
        [lang for lang, words in detection.evidence if words] or [detection.language]))

    # --- 4. FAST PATH ------------------------------------------------------
    # Confident English, no mixing, nothing suspicious: leave immediately.
    if (detection.language == "en" and detection.confidence >= 0.6
            and not detection.code_switched and not report.suspicious
            and not applied_phrases):
        # Still expand texting shorthand: "can u chek d file" is English, and
        # leaving it raw makes the intent parser work harder for no reason.
        # Pidgin and idiom rules are skipped -- they are the expensive ones,
        # and by definition this is not Pidgin.
        quick = _normalize.normalise(working, pidgin=False, idioms=False)
        return Understanding(
            raw_text=raw, english=quick.text, language="en", languages=languages,
            script=detection.script, confidence=min(1.0, detection.confidence + 0.05),
            language_confidence=detection.confidence, fast_path=True,
            engine="fast-path", latency_ms=(time.perf_counter() - started) * 1000,
            injection_markers=report.injection_markers,
            suspicious=report.suspicious, applied=quick.applied)

    # --- 5. Protect --------------------------------------------------------
    entities = _protect.BASE_ENTITIES + _protect.runtime_entities()
    guard = _protect.protect(working, entities=entities)

    # A masked secret must never leave the machine, whatever the policy says.
    has_secret = "secret" in guard.kinds.values()
    local_only = _local_only() or has_secret

    # --- 6. Normalise ------------------------------------------------------
    normalised = _normalize.normalise(
        _normalize.collapse_repeats(guard.text),
        pidgin=detection.language in ("pcm", "en", "unknown") or detection.code_switched)

    # --- 7. Translate ------------------------------------------------------
    source = detection.language
    if source in ("en", "pcm") and not detection.code_switched:
        # Rules already produced English; a model would only add latency and
        # risk. This is a real translation, not a skipped one.
        result = _translate.Translation(normalised.text, True, "rules",
                                        confidence=0.9)
    else:
        result = _translate.translate(normalised.text, source, target_language,
                                      local_only=local_only)

    english = guard.restore(result.text)

    # --- 8. Verify ---------------------------------------------------------
    checked = _verify.verify(working, english, protected=guard,
                             source_language=source)

    # Injection does not become trustworthy by being translated.
    translated_markers = _safety.scan_injection(english)
    markers = tuple(dict.fromkeys(report.injection_markers + translated_markers))

    issues = list(checked.issues)
    if not result.ok and source not in ("en", "pcm"):
        issues.append(result.detail or "translation unavailable")

    language_confidence = detection.confidence
    translation_confidence = result.confidence if result.ok else 0.2
    semantic_confidence = checked.confidence

    # The weakest link decides. Averaging lets a confident detector hide a
    # failed negation check, which is the one thing that must never happen.
    overall = min(
        (language_confidence * 0.6 + 0.4),   # detection alone never vetoes
        translation_confidence,
        semantic_confidence,
    )
    if checked.checks.get("negation") is False:
        overall = min(overall, 0.2)

    # --- 9. Back-translation, only when it earns its cost -----------------
    # Round-tripping doubles latency, so it runs only on input that is
    # already doubtful. On confident input it would be a tax on every turn
    # for a confirmation nobody needed.
    if (_verify.should_back_translate(overall, sensitive=False)
            and source not in ("en", "pcm", "unknown", "")):
        try:
            round_trip = _verify.back_translate_check(working, english, source)
            if not round_trip.ok:
                issues.extend(round_trip.issues)
                overall = min(overall, round_trip.confidence)
            else:
                # Agreement is mild evidence, not a licence. It can lift a
                # borderline reading, never make an uncertain one certain.
                overall = min(1.0, overall + min(0.1, round_trip.confidence * 0.1))
        except Exception:  # noqa: BLE001 -- verification must never break a turn
            pass

    return Understanding(
        raw_text=raw, english=english, language=source, languages=languages,
        script=detection.script, code_switched=detection.code_switched,
        confidence=round(max(0.0, min(1.0, overall)), 3),
        language_confidence=language_confidence,
        translation_confidence=translation_confidence,
        semantic_confidence=semantic_confidence,
        engine=result.engine, fast_path=False,
        latency_ms=(time.perf_counter() - started) * 1000,
        issues=issues, suspicious=report.suspicious or bool(markers),
        injection_markers=markers,
        entities={t: v for t, v in guard.values.items()
                  if guard.kinds.get(t) == "entity"},
        applied=applied_phrases + normalised.applied)


def translate_to_english(text: str) -> str:
    """Explicit translation. Distinct from understanding, per the brief."""
    return understand_text(text).english


def translate(text: str, target_language: str) -> _translate.Translation:
    """Explicit output-language translation, for "tell him in French".

    Exported from the package as `translate_text`, because the name
    `translate` also belongs to the submodule and having both meant
    `language.translate` resolved differently depending on import order.
    """
    detection = _detect.detect(str(text or ""), segment=False)
    return _translate.translate(str(text or ""), detection.language,
                                target_language, local_only=_local_only())


def normalize_to_plain_english(text: str) -> str:
    return _normalize.normalise(str(text or "")).text


def diagnostics(text: str) -> dict[str, Any]:
    """What `ZENO language debug on` shows. Metadata, never hidden reasoning."""
    understanding = understand_text(text)
    detection = _detect.detect(str(text or ""))
    return {
        "input": text,
        "detection": detection.as_dict(),
        "understanding": understanding.as_dict(),
        "engines": _translate.health(),
    }


def status() -> dict[str, Any]:
    """`zeno language status`. Never claims a model that is not installed."""
    from reyes_agent import config

    engines = _translate.health()
    installed = [e for e in engines if e["state"] == "healthy"]
    return {
        "enabled": _enabled(),
        "default_response_language": getattr(config, "LANGUAGE_DEFAULT_RESPONSE", "en"),
        "privacy": str(getattr(config, "LANGUAGE_PRIVACY", "LOCAL_PREFERRED")).upper(),
        "detector": "rules+unicode (local, no download)",
        "translation_engines": engines,
        "translation_ready": bool(installed),
        "semantic_verifier": "structural + token overlap"
                             if _verify._scorer is None else "model",
        "owner_phrases": len(_memory.get_memory().all(limit=1000)),
        "note": "Understanding is best-effort and reports its own confidence. "
                "No claim of universal coverage.",
    }
