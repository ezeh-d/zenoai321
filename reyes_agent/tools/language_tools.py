"""Explicit language capabilities the owner can ask for by name.

WHY THESE ARE SEPARATE FROM THE AUTOMATIC ENGINE
------------------------------------------------
Every turn already passes through the language engine silently -- input is
understood in English before ZENO reasons (see agent.py). That is the DEFAULT
behaviour, and it is invisible on purpose.

These tools are the EXPLICIT half: the moments the owner addresses language
itself rather than just speaking one. "Translate this into French",
"what does this Yoruba phrase mean?", "when I say 'bring it out' I mean give
me the full output". Without tools the model has no way to act on those, so
the engine's own functions are surfaced here.

Understanding stays automatic and English-by-default; producing another
language, or explaining one, is always a deliberate request -- which is
exactly the line the brief draws between UNDERSTANDING mode and TRANSLATION
OUTPUT mode.
"""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="translate_text",
    description=(
        "Translate text INTO a named language and show the result. Use ONLY "
        "when the owner explicitly asks for another language -- 'translate "
        "this to French', 'tell him in Yoruba', 'say it in Spanish'. ZENO "
        "understands every language automatically and answers in English by "
        "default; this is for when a different OUTPUT language is asked for. "
        "Returns the translation, or says plainly when no engine can do that "
        "language pair."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to translate."},
            "target_language": {
                "type": "string",
                "description": "Language to translate INTO, e.g. 'French', 'Yoruba', 'es'.",
            },
        },
        "required": ["text", "target_language"],
    },
)
def translate_text(text: str, target_language: str) -> str:
    from reyes_agent import language

    target = str(target_language or "").strip()
    if not str(text or "").strip():
        return "Nothing to translate."
    if not target:
        return "Which language should I translate it into?"

    result = language.translate_text(str(text), target)
    if not result.ok:
        # Honest failure: the most common cause is that translating INTO a
        # language needs the cloud model, and privacy is set to local-only.
        detail = result.detail or "no translation engine could do that language"
        return (f"I couldn't translate that into {target}: {detail}. "
                "I understood it fine -- I just can't produce that language "
                "right now (check LANGUAGE_PRIVACY if it should use the cloud model).")
    return f"In {target}:\n\n{result.text}"


@register(
    name="explain_language",
    description=(
        "Explain the LANGUAGE of some text rather than acting on it: what "
        "language/script it is, its meaning in English, and whether it mixes "
        "languages. Use for 'what language is this?', 'what does this phrase "
        "mean?', 'what does abeg mean?'. Reports its own confidence and says "
        "'uncertain' rather than inventing a language."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The word, phrase or sentence to explain."},
        },
        "required": ["text"],
    },
)
def explain_language(text: str) -> str:
    from reyes_agent import language
    from reyes_agent.language import detect

    raw = str(text or "").strip()
    if not raw:
        return "Give me a word or phrase to explain."

    detection = detect.detect(raw)
    understanding = language.understand_text(raw)

    lines = []
    if detection.language == "unknown":
        lines.append("Language: uncertain -- I can't confidently name it.")
    else:
        conf = detection.confidence
        hedge = "" if conf >= 0.8 else " (fairly confident)" if conf >= 0.55 else " (uncertain)"
        lines.append(f"Language: {detection.language}{hedge}")
    lines.append(f"Script: {detection.script or 'Latin'}")
    if detection.code_switched:
        langs = ", ".join(dict.fromkeys(
            l for l, w in detection.evidence if w)) or "more than one"
        lines.append(f"This mixes languages ({langs}).")
    if detection.candidates and detection.language != "en":
        alts = ", ".join(f"{c}" for c, _ in detection.candidates[:3])
        lines.append(f"Best guesses in order: {alts}")

    if understanding.english and understanding.english.strip().casefold() != raw.casefold():
        lines.append(f"\nIn English it means: {understanding.english}")
    if understanding.issues:
        lines.append(f"Caveat: {understanding.issues[0]}")
    return "\n".join(lines)


@register(
    name="remember_phrase",
    description=(
        "Remember what the OWNER means by a specific phrase, so ZENO reads it "
        "their way next time. Use when they define their own shorthand: 'when "
        "I say bring it out I mean give me the full output', 'by check am I "
        "mean inspect it'. Scoped to this owner and reversible; it never "
        "changes what the phrase means for anyone else."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "phrase": {"type": "string", "description": "The owner's phrase, e.g. 'bring it out'."},
            "meaning": {"type": "string", "description": "What they mean by it, in plain English."},
        },
        "required": ["phrase", "meaning"],
    },
)
def remember_phrase(phrase: str, meaning: str) -> str:
    from reyes_agent.language import memory

    phrase = str(phrase or "").strip()
    meaning = str(meaning or "").strip()
    if not phrase or not meaning:
        return "I need both the phrase and what it means."
    if phrase.casefold() == meaning.casefold():
        return "That phrase and meaning are the same -- nothing to learn."

    ok = memory.get_memory().teach(phrase, meaning, source="taught")
    if not ok:
        return "I couldn't store that phrase."
    return (f"Got it -- when you say \"{phrase}\" I'll take it to mean "
            f"\"{meaning}\". Say 'that's wrong' to correct me, or ask me to "
            "clear your learned phrases to remove it.")


@register(
    name="language_diagnostics",
    description=(
        "Show how the language engine is handling some text, or its overall "
        "status: detected language, translation engine, confidence, and "
        "timing. Use for 'language debug', 'why did you read that in "
        "English?', 'what languages can you do?'. Metadata only -- never "
        "hidden reasoning."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Optional text to trace through the engine. Omit for overall status.",
            },
        },
    },
)
def language_diagnostics(text: str = "") -> str:
    from reyes_agent import language

    raw = str(text or "").strip()
    if not raw:
        report = language.status()
        engines = ", ".join(
            f"{e['engine']}({e['state']})" for e in report.get("translation_engines", []))
        return (
            f"Language engine: {'on' if report.get('enabled') else 'off'}\n"
            f"Default reply language: {report.get('default_response_language')}\n"
            f"Privacy: {report.get('privacy')}\n"
            f"Translation engines: {engines or 'none'}\n"
            f"Owner phrases learned: {report.get('owner_phrases', 0)}\n"
            f"{report.get('note', '')}")

    trace = language.diagnostics(raw)
    u = trace.get("understanding", {})
    return (
        f"Input: {raw}\n"
        f"Detected: {u.get('language')} ({u.get('script')}), "
        f"confidence {u.get('confidence')}\n"
        f"Code-switched: {u.get('code_switched')}\n"
        f"English meaning: {u.get('english_meaning')}\n"
        f"Engine: {u.get('engine')}  |  fast path: {u.get('fast_path')}  |  "
        f"{u.get('latency_ms')} ms\n"
        f"Issues: {u.get('issues') or 'none'}")
