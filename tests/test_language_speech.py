"""Speech understanding, document chunking, back-translation and candidates.

The safety-critical assertions here are the ones about PARTIAL transcripts and
about candidate conflict. Streaming STT emits "delete the old" on its way to
"delete the old backup"; acting on the partial deletes the wrong thing.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.language import chunk, speech, verify  # noqa: E402


# --- speech: mishearing repair -------------------------------------------
@pytest.mark.parametrize("heard,expected", [
    ("open cloud", "open Claude"),
    ("open claud", "open Claude"),
    ("open chrom", "open Chrome"),
    ("open discort", "open Discord"),
])
def test_a_misheard_name_after_a_command_verb_is_repaired(heard, expected):
    """The brief's own example: "open Claude" transcribed as "open cloud"."""
    fixed, corrections = speech.repair_names(heard)
    assert fixed == expected
    assert corrections


@pytest.mark.parametrize("text", [
    "the cloud is down",            # no command verb: leave it alone
    "our cloud provider is slow",
    "open window",                  # ordinary word close to a product name
    "open the file",
    "check the folder",
])
def test_ordinary_language_is_never_rewritten(text):
    fixed, corrections = speech.repair_names(text)
    assert fixed == text
    assert corrections == []


def test_a_name_already_correct_is_left_alone():
    fixed, corrections = speech.repair_names("open Chrome")
    assert fixed == "open Chrome" and corrections == []


# --- speech: silence and stutter -----------------------------------------
@pytest.mark.parametrize("transcript", ["you", "Thank you.", "", "   ", "uhh", "hmm"])
def test_whisper_silence_hallucinations_are_treated_as_noise(transcript):
    """An empty room reliably transcribes as "you" or "Thank you"."""
    assert speech.is_noise(transcript) is True


@pytest.mark.parametrize("transcript", ["open Chrome", "delete the backup", "yes please"])
def test_real_speech_is_not_treated_as_noise(transcript):
    assert speech.is_noise(transcript) is False


def test_a_stutter_is_collapsed_but_emphasis_is_kept():
    assert speech.collapse_stutter("open open open Chrome") == "open Chrome"
    assert speech.collapse_stutter("very very good") == "very very good"


# --- speech: partial transcripts ------------------------------------------
def test_a_partial_transcript_can_never_authorise_a_sensitive_action():
    """"delete the old backup" passes through "delete the old" on its way."""
    from reyes_agent.language.engine import Understanding

    confident = Understanding(raw_text="x", english="delete the old", language="en",
                              confidence=1.0)
    partial = speech.SpeechUnderstanding("delete the old", confident,
                                         stage=speech.PARTIAL)
    final = speech.SpeechUnderstanding("delete the old backup", confident,
                                       stage=speech.FINAL)
    assert partial.safe_for_sensitive_action is False
    assert final.safe_for_sensitive_action is True


# --- speech: language stabilisation ---------------------------------------
def test_the_language_label_does_not_flicker():
    """Whisper re-detects per chunk and changes its mind mid-sentence."""
    stabiliser = speech.LanguageStabiliser(needed=3)
    assert stabiliser.observe("fr") == ""
    assert stabiliser.observe("en") == ""
    assert stabiliser.observe("fr") == ""
    for _ in range(3):
        stabiliser.observe("fr")
    assert stabiliser.settled == "fr"


def test_the_stabiliser_holds_its_answer_through_one_disagreement():
    stabiliser = speech.LanguageStabiliser(needed=3)
    for _ in range(3):
        stabiliser.observe("yo")
    assert stabiliser.settled == "yo"
    stabiliser.observe("en")
    assert stabiliser.settled == "yo"


# --- the STT seam ---------------------------------------------------------
def test_the_stt_manager_passes_the_detected_language_through():
    """It used to drop it. Whisper's acoustic language guess is the one
    signal a text detector cannot derive, and it was computed then discarded."""
    import inspect

    from reyes_agent.voice.stt import manager

    source = inspect.getsource(manager.transcribe_result)
    assert '"language"' in source, "the STT seam drops the detected language"
    assert '"transcript"' in source and '"confidence"' in source, \
        "the existing public seam must not change"


# --- document chunking ----------------------------------------------------
def test_short_text_is_one_chunk():
    assert len(chunk.split("Open Chrome.")) == 1


def test_long_text_is_split_at_paragraph_boundaries():
    text = "\n\n".join(f"Paragraph {i}. " + ("word " * 60) for i in range(8))
    chunks = chunk.split(text, limit=800)
    assert len(chunks) > 1
    for piece in chunks:
        assert len(piece.text) <= 900


def test_a_sentence_is_never_cut_in_half():
    text = ". ".join(f"This is sentence number {i} and it says something" for i in range(60)) + "."
    for piece in chunk.split(text, limit=500):
        stripped = piece.text.strip()
        # Every chunk should end at a sentence boundary or be the last one.
        assert stripped
        assert not stripped.endswith(" and")


def test_chunks_carry_context_from_the_previous_one():
    text = "\n\n".join(f"Paragraph {i}. " + ("word " * 60) for i in range(5))
    chunks = chunk.split(text, limit=600, overlap=100)
    assert chunks[0].context_before == ""
    assert chunks[1].context_before, "later chunks need the previous tail as context"


def test_text_with_no_punctuation_still_splits_without_cutting_a_word():
    text = "word " * 900
    for piece in chunk.split(text, limit=400):
        assert not piece.text.startswith("ord")


def test_a_glossary_keeps_a_term_consistent():
    glossary = chunk.Glossary()
    glossary.learn("Council Mode", "Council Mode")
    glossary.learn("Council Mode", "Mode du Conseil")     # ignored: first wins
    assert glossary.apply("Use Council Mode now") == "Use Council Mode now"
    assert glossary.terms["Council Mode"] == "Council Mode"


def test_a_failed_chunk_is_reported_not_silently_dropped():
    """Silently omitting a paragraph is the worst failure for a document."""
    calls = {"n": 0}

    def flaky(text, conversation_context=""):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("engine down")
        from reyes_agent.language.engine import Understanding
        return Understanding(raw_text=text, english=text, language="en", confidence=1.0)

    text = "\n\n".join(f"Paragraph {i}. " + ("word " * 60) for i in range(4))
    result = chunk.understand_document(text, limit=500, understand=flaky)
    assert result.failed, "a failed chunk must be reported"
    assert result.complete is False
    # The original text is kept in place so the document stays whole.
    assert "Paragraph" in result.english


# --- back-translation -----------------------------------------------------
def test_back_translation_is_skipped_when_confidence_is_high():
    """Doubling latency to re-confirm something already clear is a tax."""
    assert verify.should_back_translate(0.95) is False
    assert verify.should_back_translate(0.9) is False


def test_back_translation_runs_when_confidence_is_low():
    assert verify.should_back_translate(0.5) is True
    assert verify.should_back_translate(0.7, sensitive=True) is True


def test_back_translation_catches_a_flipped_negation():
    def flipping_translator(text, source, target):
        from reyes_agent.language.translate import Translation
        return Translation("supprime le fichier", True, "fake", confidence=0.9)

    checked = verify.back_translate_check(
        "ne supprime pas le fichier", "delete the file", "fr",
        translator=flipping_translator)
    assert checked.ok is False or checked.confidence < 0.5


def test_an_unavailable_reverse_engine_is_not_treated_as_a_failure():
    """No adapter for a language is not evidence the translation is wrong."""
    def unavailable(text, source, target):
        from reyes_agent.language.translate import Translation
        return Translation(text, False, "none", detail="no adapter")

    checked = verify.back_translate_check("bonjour", "hello", "fr",
                                          translator=unavailable)
    assert checked.ok is True


# --- ranked candidates ----------------------------------------------------
def test_the_candidate_that_keeps_the_negation_ranks_first():
    """`count_negation` only knows ENGLISH negators. Using it on a French
    original inverted this test and ranked "Delete the file" above
    "Do not delete the file"."""
    candidates = [verify.Candidate("Delete the file", "a", 0.8),
                  verify.Candidate("Do not delete the file", "b", 0.75)]
    for original in ("Ne supprime pas le fichier", "No borres el archivo",
                     "Make you no delete am"):
        ranked = verify.rank_candidates(original, list(candidates))
        assert ranked[0].text == "Do not delete the file", original


def test_an_unnegated_original_ranks_the_unnegated_reading_first():
    candidates = [verify.Candidate("Delete the file", "a", 0.8),
                  verify.Candidate("Do not delete the file", "b", 0.75)]
    ranked = verify.rank_candidates("Supprime le fichier", candidates)
    assert ranked[0].text == "Delete the file"


def test_readings_that_disagree_about_negation_are_a_conflict():
    conflict, reason = verify.candidates_conflict([
        verify.Candidate("Delete the file", "a", 0.8),
        verify.Candidate("Do not delete the file", "b", 0.79)])
    assert conflict is True and "negated" in reason


def test_readings_that_disagree_about_the_verb_are_a_conflict():
    conflict, reason = verify.candidates_conflict([
        verify.Candidate("Delete the report", "a", 0.8),
        verify.Candidate("Send the report", "b", 0.78)])
    assert conflict is True and "action" in reason


def test_wording_differences_are_not_a_conflict():
    conflict, _ = verify.candidates_conflict([
        verify.Candidate("Open Chrome", "a", 0.9),
        verify.Candidate("Open Chrome please", "b", 0.85)])
    assert conflict is False


# --- setup CLI ------------------------------------------------------------
def test_the_installer_never_downloads_without_explicit_confirmation():
    from reyes_agent.language import cli

    outcome = cli.install("standard")
    assert outcome["ok"] is False
    assert outcome.get("needs_confirmation") is True


def test_an_unknown_tier_is_refused():
    from reyes_agent.language import cli

    assert cli.install("enormous", yes=True)["ok"] is False


def test_status_reads_installed_size_from_disk_rather_than_claiming_it():
    from reyes_agent.language import cli

    reported = cli.status()
    for tier in reported["tiers"].values():
        for model in tier["models"]:
            if not model["installed"]:
                assert model["size_mb"] == 0, "an absent model must not report a size"


def test_the_smoke_test_actually_exercises_the_engine():
    from reyes_agent.language import cli

    outcome = cli.smoke_test()
    assert outcome["total"] == 3
    assert all("english" in r or "error" in r for r in outcome["results"])


# --- HTTP surface ---------------------------------------------------------
def _client():
    from fastapi.testclient import TestClient

    from reyes_agent import web
    return TestClient(web.app, client=("127.0.0.1", 45678))


def test_language_routes_are_registered_and_work():
    client = _client()
    assert client.get("/api/language/status").status_code == 200
    body = client.post("/api/language/understand",
                       json={"text": "Abeg open Chrome"}).json()
    assert "Please open Chrome" in body["english_meaning"]
    assert body["language"] == "pcm"


def test_language_routes_are_not_reachable_remotely():
    from reyes_agent.remote_access.boundary import remote_path_allowed

    for path in ("/api/language/status", "/api/language/understand",
                 "/api/language/teach", "/api/language/phrases/clear"):
        assert remote_path_allowed(path) is False, path


def test_teaching_requires_both_halves():
    client = _client()
    assert client.post("/api/language/teach", json={"phrase": "x"}).status_code == 400


# --- streaming STT wiring -------------------------------------------------
def test_streaming_uses_the_transcript_it_already_has(monkeypatch):
    """`understand_audio` transcribes; streaming has ALREADY transcribed.

    Re-transcribing would discard the entire latency win -- the audio went up
    while the owner was still speaking -- and pay twice for the same words.

    Checked by BEHAVIOUR: the STT manager is replaced with a function that
    fails the test if it is called. The first version of this test grepped the
    source for "transcribe", which the docstring uses four times while
    explaining that it does not transcribe.
    """
    from reyes_agent.voice.stt import manager

    def must_not_be_called(_audio):
        raise AssertionError("understand_transcript re-transcribed the audio")

    monkeypatch.setattr(manager, "transcribe_result", must_not_be_called)
    heard = speech.understand_transcript("abeg open chrome")
    assert "Please open Chrome" in heard.english


def test_a_streamed_pidgin_command_reaches_the_brain_in_english():
    heard = speech.understand_transcript(
        "abeg open chrom make I check am",
        backend="deepgram-streaming", confidence=0.94, latency_s=0.31)
    assert "Please open Chrome" in heard.english
    assert heard.understanding.language == "pcm"
    assert ("chrom", "Chrome") in heard.corrections


def test_a_streamed_partial_can_never_authorise_an_action():
    partial = speech.understand_transcript("abeg delete am", stage=speech.PARTIAL)
    final = speech.understand_transcript("abeg delete am", stage=speech.FINAL)
    assert partial.safe_for_sensitive_action is False
    assert final.stage == speech.FINAL


def test_an_interim_result_contributes_language_evidence_and_nothing_else():
    speech.reset_for_tests()
    for _ in range(3):
        speech.observe_partial("", audio_language="fr")
    assert speech._stabiliser.settled == "fr"
    speech.reset_for_tests()


def test_the_wake_word_survives_the_language_engine():
    """Brief 34: ZENO's wake word must stay identifiable.

    It is matched against the RAW transcript before any of this runs, and it
    is also a protected entity so translation cannot move or rewrite it.
    """
    heard = speech.understand_transcript("ZENO abeg open chrom")
    assert "ZENO" in heard.english


def _runtime_source() -> str:
    """The runtime MODULE, not the class.

    The turn handler is a nested function, so `inspect.getsource` on
    `RemoteMicRuntime` contains neither the wake match nor the language call.
    """
    import pathlib

    from reyes_agent.remote_mic import runtime

    return pathlib.Path(runtime.__file__).read_text(encoding="utf-8")


def test_the_runtime_understands_after_wake_matching_not_before():
    """Order matters. Matching the wake word against TRANSLATED text would
    mean a mistranslation could hide the wake word entirely."""
    source = _runtime_source()
    assert source.index("_WAKE.match(transcript)") < source.index("understand_transcript"), \
        "the wake word must be matched before the language engine runs"


def test_the_runtime_keeps_the_owners_words_when_confidence_is_low():
    """A low-confidence rewrite is worse than the original: the brain can ask
    about an odd sentence, it cannot recover a wrongly rewritten meaning."""
    assert "heard.confidence >= 0.5" in _runtime_source()


# --- status and the web panel -------------------------------------------
def test_status_reports_speech_state():
    """The report showed a language engine with no voice at all.

    `status()` omitted speech entirely, so `zeno language status` and the web
    panel could not tell an installed multilingual model from none.
    """
    from reyes_agent.language import status

    speech_state = status()["speech"]
    assert speech_state["state"] in {"READY", "STANDBY", "NOT_CONFIGURED",
                                     "UNAVAILABLE", "UNKNOWN"}
    assert "local" in speech_state and "cloud" in speech_state


def test_status_reads_the_real_manager_shape():
    """The first version guessed {"backends": {"faster_whisper": ...}}.

    The manager actually reports {"primary": ..., "fallback": ...}, so it
    reported UNKNOWN with an empty model while a working multilingual model
    was installed. Guarding the shape, not the values.
    """
    from reyes_agent.voice.stt import manager

    report = manager.status()
    assert "primary" in report and "fallback" in report, (
        "the STT manager shape changed; language status reads primary/fallback")


def test_an_english_only_model_is_not_called_multilingual():
    """`base.en` transcribes English only. Reporting it as multilingual would
    be exactly the overclaim the brief forbids."""
    from reyes_agent.language.engine import _speech_status

    state = _speech_status()
    model = state["local"]["model"]
    if model.endswith(".en"):
        assert state["multilingual_local"] is False
    elif model:
        assert state["multilingual_local"] is True


def test_the_web_app_renders_the_language_panel():
    """Five language routes existed and nothing displayed them."""
    import pathlib

    page = pathlib.Path("reyes_agent/static/app.html").read_text(encoding="utf-8")
    assert "Language intelligence" in page
    # Wired to the REAL routes, not placeholder markup.
    assert "/api/language/status" in page
    assert "/api/language/understand" in page


def test_the_language_panel_shows_the_original_beside_the_english():
    """If ZENO misreads a sentence, the owner can only see it by comparing."""
    import pathlib

    page = pathlib.Path("reyes_agent/static/app.html").read_text(encoding="utf-8")
    assert "You said" in page and "ZENO understood" in page
