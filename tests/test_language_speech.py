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
