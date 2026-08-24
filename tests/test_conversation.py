"""Contracts for the Pack 6 human-conversation engines (pure logic + safety)."""

from __future__ import annotations

from reyes_agent.conversation import identity, social, explanation, consent
from reyes_agent.conversation.planner import (
    ConversationResponsePlanner, STAY_SILENT, EXPLAIN, ANSWER, CLARIFY, SUMMARIZE, CORRECT)


# --- SpeakerIdentityManager -------------------------------------------------
def test_identity_starts_as_session_label():
    m = identity.SpeakerIdentityManager()
    m.observe("SPEAKER_01")
    m.observe("SPEAKER_02")
    assert m.label_for("SPEAKER_02") == "Speaker 2"
    assert m.roster()[0]["level"] == identity.SESSION_LABEL


def test_identity_introduce_and_owner_confirm():
    m = identity.SpeakerIdentityManager()
    m.observe("SPEAKER_01")
    m.introduce("SPEAKER_01", "Ayo")
    assert m.label_for("SPEAKER_01") == "Ayo"
    m.owner_identify("SPEAKER_02", "Bello", relationship="lecturer", title="Dr.")
    assert m.label_for("SPEAKER_02") == "Dr. Bello"
    assert m.find_by_name("bello")[0].level == identity.OWNER_CONFIRMED


def test_identity_never_downgrades():
    m = identity.SpeakerIdentityManager()
    m.owner_identify("S1", "Bello")               # OWNER_CONFIRMED
    m.introduce("S1", "Bello")                    # weaker -> must not downgrade
    assert m.find_by_name("bello")[0].level == identity.OWNER_CONFIRMED


def test_identity_forget():
    m = identity.SpeakerIdentityManager()
    m.introduce("S1", "Ayo")
    assert m.forget("S1") is True and m.find_by_name("ayo") == []


# --- AddresseeResolver ------------------------------------------------------
def test_addressee_leading_name():
    r = social.AddresseeResolver()
    assert r.resolve("STARK, what do you think?", agents=("STARK",)).target == "agent:STARK"
    assert r.resolve("Dr. Bello, could you clarify?", humans=("Dr. Bello",)).target == "human:Dr. Bello"
    assert r.resolve("ZENO, open Slack").target == social.ZENO


def test_addressee_group_mode_stays_unassuming():
    r = social.AddresseeResolver()
    # A question with no explicit target in a meeting is for the room, not ZENO.
    a = r.resolve("How does the routing work?", mode="meeting")
    assert a.target in (social.ROOM, social.UNKNOWN_ADDRESSEE)
    # One-to-one, the same question is for ZENO.
    assert r.resolve("How does the routing work?", mode="normal").target == social.ZENO


# --- SocialRegisterEngine ---------------------------------------------------
def test_register_from_relationship_and_setting():
    e = social.SocialRegisterEngine()
    assert e.select(relationship="friend") == social.FRIENDLY
    assert e.select(relationship="lecturer") == social.ACADEMIC
    assert e.select(relationship="ceo") == social.EXECUTIVE
    assert e.select(relationship="unknown") == social.NEUTRAL
    # Setting overrides relationship default.
    assert e.select(relationship="friend", setting="meeting") == social.PROFESSIONAL
    # An explicit request wins over everything.
    assert e.select(relationship="friend", requested="FORMAL") == social.FORMAL


# --- StayQuietPolicy --------------------------------------------------------
def test_quiet_never_answers_for_someone_else():
    q = social.StayQuietPolicy()
    other = social.Addressee("human:Ayo", 0.9, "x")
    assert q.decide(other, mode="normal").speak is False


def test_quiet_silent_in_meeting_unless_wanted():
    q = social.StayQuietPolicy()
    room = social.Addressee(social.ROOM, 0.4, "x")
    assert q.decide(room, mode="meeting").speak is False
    assert q.decide(room, mode="meeting", critical=True).speak is True
    zeno = social.Addressee(social.ZENO, 0.9, "x")
    assert q.decide(zeno, mode="meeting").speak is True


# --- ExplanationAdapter -----------------------------------------------------
def test_explanation_beginner_vs_expert():
    a = explanation.ExplanationAdapter()
    beg = a.strategy(explanation.BEGINNER)
    assert beg.use_analogy and not beg.use_jargon
    exp = a.strategy(explanation.EXPERT)
    assert exp.use_jargon and "implementation" in exp.structure


def test_explanation_detail_requests():
    a = explanation.ExplanationAdapter()
    assert a.strategy(explanation.INTERMEDIATE, detail="simpler").use_jargon is False
    assert a.strategy(explanation.INTERMEDIATE, detail="technical").use_jargon is True
    assert a.strategy(explanation.BEGINNER, detail="briefly").detail == "brief"


def test_explanation_executive_purpose_structure():
    a = explanation.ExplanationAdapter()
    strat = a.strategy(explanation.FAMILIAR, purpose="executive")
    assert strat.structure[0] == "what it is" and "risk" in strat.structure


# --- ConsentStateManager ----------------------------------------------------
def test_consent_conservative_defaults():
    c = consent.ConsentStateManager()
    assert c.allowed(consent.AUDIO_PROCESSING) is True
    assert c.allowed(consent.RECORDING) is False
    assert c.allowed(consent.SPEAKER_ENROLLMENT) is False


def test_consent_grant_revoke_and_clear():
    c = consent.ConsentStateManager()
    assert c.grant(consent.RECORDING) is True and c.allowed(consent.RECORDING) is True
    c.revoke(consent.RECORDING)
    assert c.allowed(consent.RECORDING) is False
    c.grant(consent.TRANSCRIPT_RETENTION)
    c.set_privacy_mode(consent.NO_TRANSCRIPT_STORAGE)
    assert c.allowed(consent.TRANSCRIPT_RETENTION) is False
    c.grant(consent.RECORDING); c.clear()
    assert c.allowed(consent.RECORDING) is False


def test_consent_unknown_flag_is_ignored():
    c = consent.ConsentStateManager()
    assert c.grant("mind_reading") is False


# --- ConversationResponsePlanner (composition) ------------------------------
def test_planner_stays_silent_in_meeting_when_not_addressed():
    p = ConversationResponsePlanner()
    plan = p.plan("How does the phone connect?", mode="meeting")
    assert plan.should_speak is False and plan.response_type == STAY_SILENT


def test_planner_answers_agent_address_by_staying_out():
    p = ConversationResponsePlanner()
    plan = p.plan("Dr. Bello, what do you think?", humans=("Dr. Bello",), mode="group")
    assert plan.should_speak is False           # ZENO does not answer for a human


def test_planner_explains_with_register_and_detail():
    p = ConversationResponsePlanner()
    plan = p.plan("ZENO, explain the phone system", relationship="lecturer",
                  audience_level=explanation.ADVANCED, detail="technical")
    assert plan.should_speak is True
    assert plan.response_type == EXPLAIN
    assert plan.register == social.ACADEMIC
    assert plan.detail_level == "technical"
    assert plan.explanation["use_jargon"] is True


def test_planner_answer_and_summarize_and_correct():
    p = ConversationResponsePlanner()
    assert p.plan("ZENO, what time is it?").response_type == ANSWER
    assert p.plan("ZENO, what did I miss?").response_type == SUMMARIZE
    assert p.plan("ZENO, no I meant the laptop").response_type == CORRECT


def test_planner_clarifies_ambiguous_reference():
    p = ConversationResponsePlanner()
    plan = p.plan("ZENO, tell him", ambiguous_reference=True)
    assert plan.response_type == CLARIFY


def test_planner_never_raises_on_garbage():
    p = ConversationResponsePlanner()
    plan = p.plan(None)  # type: ignore[arg-type]
    assert plan.response_type in {ANSWER, STAY_SILENT, "ACKNOWLEDGE"}
