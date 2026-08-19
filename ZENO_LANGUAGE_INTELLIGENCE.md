# ZENO Universal Language Intelligence v1

## What it does

Input in any language → clear English → ZENO reasons normally → replies in
English. The conversion happens **once**, in `agent.py`, so every agent, tool,
router and permission gate downstream receives English without knowing this
layer exists.

```
raw input
  → sanitise        unicode, invisible characters, injection scan
  → owner phrases   what this owner means by a phrase
  → detect          language, script, code-switching
  → FAST PATH       confident English exits here in ~3ms
  → protect         secrets, code, entities, numbers → placeholders
  → normalise       Pidgin, slang, idiom, typos → plain English
  → translate       adapter router, local-first
  → restore         placeholders → original values
  → verify          negation, numbers, entities, imperative mood
  → Understanding
```

## Modules

| file | job |
|---|---|
| `language/safety.py` | Unicode, homoglyphs, bidi, zero-width, injection |
| `language/protect.py` | Mask what must survive translation byte-for-byte |
| `language/detect.py` | Language, script, code-switch — local, no download |
| `language/normalize.py` | Pidgin, slang, idiom, typos, fillers → plain English |
| `language/translate.py` | Adapter router, circuit breaker, local-first |
| `language/verify.py` | Did the meaning survive? |
| `language/memory.py` | Owner's own vocabulary |
| `language/engine.py` | Orchestrator, confidence, fast path |

## Models: one installed, on purpose

The brief asks for MADLAD/GlotLID/SONAR "or equivalent" and, separately, that
huge models must not be pulled without control and must not destabilise the
Windows app.

**One model is now installed** — `Systran/faster-whisper-base`, 296 MB on
disk, for multilingual speech. It was downloaded by an explicit command, not
on import or on first use, and `python -m reyes_agent.language.cli setup`
states the disk and RAM cost before doing anything.

**Text translation still ships no weights.** The architecture is adapters:

- `RuleAdapter` — Pidgin/slang/idiom → English. Offline, deterministic, ~3ms.
  A genuine translator for what it covers, not a stand-in.
- `ProviderAdapter` — ZENO's already-configured LLM. Broad coverage, no
  download. Not local, so `LANGUAGE_PRIVACY=LOCAL_ONLY` excludes it.
- `NullAdapter` — returns the original and **says `ok=False`**.

A local MADLAD or NLLB adapter drops in by subclassing `TranslationAdapter`
and calling `register()`. Nothing else changes. `verify.set_semantic_scorer()`
takes a SONAR-style model the same way.

**An adapter that cannot translate returns the original text and `ok=False`.**
It never returns a guess dressed as a translation, because callers use `ok` to
decide whether a sensitive action may proceed.

## Measured

| input | path | latency |
|---|---|---|
| `Open Chrome and check my email` | fast | **3–16 ms** |
| `Do not delete the file` | fast | **3.8 ms** |
| `Abeg open Chrome` | rules | **3–6 ms** |
| `Wetin dey happen?` | rules | **3.7 ms** |
| `Abeg open Chrome make I check something` | rules | 4.1 ms warm |

Cold start is ~1.4s once, dominated by the agent-roster read, now cached for
300s. The fast path exists because the router work took "what time is it" from
10.05s to ~1.1s, and a language layer taxing every turn would eat that back.

## Nigerian Pidgin

First-class, rule-based, offline:

| Pidgin | English |
|---|---|
| `Abeg open Chrome.` | `Please open Chrome.` |
| `Wetin dey happen?` | `What is happening?` |
| `I wan check that file.` | `I want to check that file.` |
| **`Make you no delete am.`** | **`Do not delete it.`** |
| `Shey e don finish?` | `Has it finished?` |
| `Shey you dey come?` | `Are you coming?` |
| `I don send am` | `I have sent it` |

Aspect is conjugated properly. Naive `+ed` produced *"sended"* and *"Are you
come?"*; there is now a past-participle table and a gerund rule with
consonant doubling.

## The five bugs found while building this

**1. The capability router was dead.** `agent.py` referenced `message`, which
was never bound. Every turn raised `NameError`, `except Exception` swallowed
it, and the router never ran. It was wrong in the commit that introduced it —
the 10.05s→1.1s figure was measured by calling `tools_for()` directly, so the
regression never showed up. Fixed by hoisting the existing `latest` variable.

**2. A Pidgin negation reached the brain unnormalised.** *"Make you no delete
am"* scored English on the single word "you", took the fast path untouched,
and delivered raw Pidgin negation to the reasoning layer. The fast path now
refuses when any other language has distinctive evidence.

**3. "Open Chrome" was classified Dutch.** `open` is a Dutch function word and
the sentence contains no English one, so Dutch won — and the sentence went to
a translation model, costing **4.8 seconds** to come back unchanged. English
imperatives are now markers, and a language whose only evidence is ordinary
English words cannot outrank English.

**4. Code-switch detection was wrong in both directions.** Clause-level
winners reported a switch for *"Open Chrome and check the file"* and missed
*"Abeg ouvre Chrome"* — Pidgin and French inside one clause. Now word-level
evidence, with `{en, pcm}` excluded because Pidgin is English-based.

**5. A sqlite round trip on every turn.** `LanguageMemory.apply()` opened a
connection, ran an UPDATE and selected 200 rows on every request including
plain English. Fast-path latency climbed 11ms → 31ms across three consecutive
calls. Now short-circuits on a cached count.

Plus a name collision: the package exported a function `translate` that
shadowed the submodule `translate`, so `language.translate` resolved
differently depending on import order. Exported as `translate_text`.

## Safety

**Negation is the check that matters.** "Delete the file" and "Do not delete
the file" are ~95% similar to any embedding model and are opposite
instructions, so verification is **structural first, similarity last**. A lost
negation is a hard failure that caps confidence at 0.2.

**Nothing executes here.** The engine returns an `Understanding`. The intent
parser, capability system and permission gates run afterwards, unchanged — a
sentence arriving in Yoruba gets no more authority than the same sentence in
English.

**Translation does not launder input.** The injection scan runs on the
original *and* the English. A hostile sentence in Yoruba is still hostile in
English, and arrives looking as clean as a legitimate one.

**Secrets never leave the machine.** A detected API key is masked before any
adapter sees it, and its presence forces `local_only` regardless of the
configured privacy policy.

**NFC, not NFKC.** NFKC folds characters that are distinct letters in other
scripts. Yoruba `ẹ` and `e` are different letters and both survive.

**ZWJ/ZWNJ are kept.** They are meaningful in Arabic, Persian and Indic
scripts; stripping them as "invisible characters" would corrupt those
languages.

## Configuration

```
LANGUAGE_ENGINE_ENABLED=true
LANGUAGE_DEFAULT_RESPONSE=en
LANGUAGE_PRIVACY=LOCAL_PREFERRED   # LOCAL_ONLY | LOCAL_PREFERRED | CLOUD_ALLOWED
LANGUAGE_SEMANTIC_VERIFY=true
LANGUAGE_OWNER_MEMORY=true
LANGUAGE_DEBUG=false
```

## Tests

**141** across `tests/test_language_engine.py` (94) and
`tests/test_language_speech.py` (47). Full suite **1346 passing**, up from
1103 at the start of this work.

Weighted deliberately: negation, numbers, entities and code get exhaustive
coverage; prose quality gets spot checks. An awkward translation is a quality
problem, an inverted negation is a destroyed filesystem.

## KNOWN LIMITATIONS

- **Latin-script languages are identified by function words**, so short input
  in a language whose markers are absent returns `unknown` rather than a
  guess. That is deliberate, but it means coverage is *good* for the ~16
  listed languages and *absent* for others until an adapter is installed.
- **Non-Latin scripts identify the script confidently and the language only
  approximately** — Arabic vs Persian vs Urdu, Chinese vs Japanese in Han.
- **Semantic verification is token overlap**, not a multilingual embedding
  model. The structural checks do the safety-critical work; similarity is a
  weak signal until SONAR or equivalent is registered.
- **Translation for languages outside the rule set requires the LLM
  provider.** With `LANGUAGE_PRIVACY=LOCAL_ONLY` and no local adapter, those
  return `ok=False` and the original text.
- **Dialect is not identified.** The brief asks for dialect awareness; this
  reports language and confidence only, rather than inventing a dialect label.
- **Tone and emoji sentiment are not implemented.**

## Speech (built)

`language/speech.py` - one entry point, `understand_audio()`, shared by the
desktop microphone, the phone microphone and the web client. It reuses
`voice/stt/manager.py` (which already had a cloud/local circuit breaker) and
adds what STT does not do:

| behaviour | why |
|---|---|
| original transcript kept beside the English | debugging, corrections, display |
| misheard names repaired | `open cloud` -> `open Claude` |
| stutters collapsed, emphasis kept | `open open open Chrome` -> `open Chrome` |
| silence hallucinations rejected | an empty room transcribes as "you" |
| **partial transcripts can never authorise an action** | `delete the old backup` passes through `delete the old` |
| language label stabilised | Whisper re-detects per chunk and flickers |

**Name repair is deliberately conservative.** A correction applies only when
the token follows a command verb *and* is close to a name ZENO actually
knows. `the cloud is down` is untouched. The threshold is **0.72**, because
that is what `cloud` -> `Claude` (0.727) needs; a sweep of 30 ordinary objects
against the entity list found exactly one collision at that level
(`window` -> `Windows`), handled by a guard list.

### Installed

**`Systran/faster-whisper-base` - ~100 languages, int8 on CPU.** 148 MB
downloaded, **296 MB on disk** (the HuggingFace cache keeps a blob and a
snapshot, and Windows without developer mode copies rather than symlinks).
Configured in `.env` and reporting `STANDBY`.

Verified on real audio generated with Windows SAPI:

```
"Please open Chrome and check my email"
  -> transcript: "Please open Chrome and check my email."
  -> language: en    latency: 6.1s (first load), backend faster-whisper-int8
```

## Documents, back-translation, candidates (built)

**`language/chunk.py`** splits at the strongest boundary available -
paragraph, then sentence, then clause, then a hard limit that still refuses
to cut mid-word. Each chunk carries the previous chunk's tail as context. A
`Glossary` fixes the first translation of each term so it stays consistent
across a document. **A failed chunk keeps its original text and is reported
by index** - silently omitting a paragraph is the worst possible failure for
a document.

**Back-translation** (`verify.back_translate_check`) round-trips the English
and compares. It runs only when confidence is already below 0.85, because
doubling latency to re-confirm something clear is a tax on every turn.

**Ranked candidates** (`verify.rank_candidates`) score each reading by its own
confidence plus agreement with the others. `candidates_conflict()` refuses to
pick when two readings disagree about **negation** or about **which verb** is
commanded - wording differences are fine, a disagreement about the action is
not.

## `zeno language` (built)

```bash
python -m reyes_agent.language.cli status
python -m reyes_agent.language.cli setup standard --yes
python -m reyes_agent.language.cli test
```

`setup` never downloads without an explicit tier *and* `--yes`, states the
disk and RAM cost first, and checks free space. `status` reads installed sizes
**off disk** rather than claiming them - an absent model reports 0 MB.

Recommended tier is chosen from real hardware: this machine (8.4 GB RAM, 4
threads, no CUDA) gets `standard`.

## Web dashboard (built)

`GET /api/language/status`, `POST /api/language/understand`,
`POST /api/language/teach`, `GET /api/language/phrases`,
`POST /api/language/phrases/clear`. All five are **desktop-only** - not
allow-listed in `remote_access.boundary`, asserted by a test.

## Three more bugs found while building this

**6. The STT seam discarded the detected language.** `transcribe_result`
narrowed its result to `{transcript, confidence}`, so Whisper's acoustic
language guess - the one signal a text detector cannot derive - was computed
and then thrown away. Now passed through additively; both original keys keep
their exact meaning.

**7. Candidate ranking inverted for every non-English negation.**
`count_negation` only knows English negators, so for *"Ne supprime pas le
fichier"* it scored the original as un-negated and **ranked "Delete the file"
above "Do not delete the file"**.

**8. Back-translation was blind to the case it exists for.** Both sides of the
round trip are in the *source* language, and the same English-only counter
reported a lost negation as preserved. *"ne supprime pas le fichier"* ->
*"supprime le fichier"* scored as fine.

## NOT YET BUILT


- **Accent-specific tuning.** Whisper handles accents as well as Whisper does;
  nothing here improves on it, and no Nigerian-accent evaluation was run.
- **Explicit output-language responses.** `translate_text` works; no command
  surfaces it, so "tell him in French" is not yet something ZENO does.
- **Tone and emoji sentiment** (§39, §71).
- **Dialect identification** (§10) — reported as language + confidence only.

## Not verified

- **No non-English speech was ever transcribed.** Only `en-US` voices are
  installed on this machine, so the multilingual model's 100-language figure
  is the model's claim, not a measurement. English audio was verified end to
  end.
- No evaluation against a labelled multilingual corpus. The accuracy claims
  are the test cases in this repository, not a benchmark.
- No load testing of the language path, and no measurement on any other
  machine.
