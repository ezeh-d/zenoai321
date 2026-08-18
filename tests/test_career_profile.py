from __future__ import annotations

import json

import pytest

from reyes_agent.career_profile import (
    AUTHENTICATION_REQUIRED,
    CareerProfileError,
    PROFILE_FIELDS,
    ZenoCareerProfile,
)
from reyes_agent.permissions import capability_for_tool
from reyes_agent.routing import capability as router
from reyes_agent.tools import GROUP_NAMES, TOOLS, group_of
from reyes_agent.tools import career_tools, subagents


@pytest.fixture()
def profile(tmp_path):
    return ZenoCareerProfile(
        tmp_path / "career" / "profile.sqlite3",
        registered_gmail=lambda: "divine.owner@gmail.com",
    )


def test_store_is_lazy_and_configured_gmail_is_masked(tmp_path):
    path = tmp_path / "career" / "profile.sqlite3"
    profile = ZenoCareerProfile(path, registered_gmail=lambda: "divine.owner@gmail.com")
    assert not path.exists()

    status = profile.status()

    assert path.exists()
    assert status["source_of_truth"] == "ZenoCareerProfile"
    assert status["registered_gmail"] != "divine.owner@gmail.com"
    assert "registered_gmail" in status["configured_fields"]
    assert "employment_history" in status["missing_fields"]


def test_only_owner_confirmed_facts_are_saved(profile):
    with pytest.raises(CareerProfileError, match="explicitly confirmed"):
        profile.update({"professional_title": "Software Engineer"}, owner_confirmed=False)

    result = profile.update(
        {
            "professional_title": "Software Engineer",
            "skills": ["Python", "Accessibility testing"],
            "certifications": [],
        },
        owner_confirmed=True,
    )

    assert set(result["updated_fields"]) == {
        "certifications", "professional_title", "skills",
    }
    assert "certifications" not in result["missing_fields"]
    read = profile.read("professional")
    assert read["profile"]["professional_title"] == "Software Engineer"
    assert read["provenance"]["professional_title"] == "owner_confirmed"
    assert profile.revision_count() == 1


@pytest.mark.parametrize(
    "fields,match",
    [
        ({"made_up_field": "value"}, "Unknown career profile"),
        ({"skills": "Python"}, "must be a list"),
        ({"contact_information": {"password": "hunter2"}}, "credential material"),
        ({"professional_summary": "api key: abcdefghijklmnop"}, "password, token, or private key"),
        ({"registered_gmail": "another@gmail.com"}, "not ZENO's configured"),
    ],
)
def test_invalid_or_sensitive_profile_data_is_rejected(profile, fields, match):
    with pytest.raises(CareerProfileError, match=match):
        profile.update(fields, owner_confirmed=True)
    assert profile.revision_count() == 0


def test_contact_values_are_masked_in_model_facing_reads(profile):
    profile.update(
        {
            "contact_information": {
                "email": "divine.owner@gmail.com",
                "phone": "+234 801 234 5678",
                "city": "Lagos",
                "country": "Nigeria",
            }
        },
        owner_confirmed=True,
    )
    result = profile.read("contact")["profile"]
    encoded = json.dumps(result)
    assert "divine.owner@gmail.com" not in encoded
    assert "+234 801 234 5678" not in encoded
    assert result["contact_information"]["city"] == "Lagos"
    assert result["contact_information"]["phone"].endswith("5678")


def test_profile_revisions_are_bounded(profile):
    for index in range(55):
        profile.update({"professional_title": f"Title {index}"}, owner_confirmed=True)
    assert profile.revision_count() == 50
    assert profile.read("professional")["profile"]["professional_title"] == "Title 54"


def test_platform_plan_has_exact_authentication_and_truth_boundaries(profile, monkeypatch):
    monkeypatch.setattr(career_tools, "get_career_profile", lambda: profile)
    plan = json.loads(career_tools.career_platform_plan("linkedin", "complete"))

    assert plan["external_state"] == "NOT_CHANGED"
    assert plan["terms_status"] == "LIVE_TERMS_CHECK_REQUIRED"
    assert plan["authentication_boundary"]["display_exactly"] == AUTHENTICATION_REQUIRED
    assert plan["sign_in"]["prefer_continue_with_google"] is True
    assert any("inventing jobs" in item for item in plan["prohibited"])
    assert "unattended submission" in plan["job_application_boundary"]


def test_career_tools_are_lazy_routed_and_permission_gated():
    names = {
        "career_profile_status", "career_profile_read", "career_profile_update",
        "career_profile_fill_field", "career_platform_plan",
    }
    assert names <= set(TOOLS)
    assert all(group_of(name) == "career" for name in names)
    assert "career" in GROUP_NAMES
    assert capability_for_tool("career_profile_update") == "filesystem_write"
    assert capability_for_tool("career_profile_fill_field") == "browser_automation"
    assert TOOLS["career_profile_update"].requires_confirmation is True

    route = router.tools_for("Complete my LinkedIn profile")
    assert "career" in route.capabilities
    assert names <= set(route.tools)
    assert "career_profile_fill_field" in route.tools
    assert "browser_click" not in route.tools
    assert route.exposed <= 12


def test_titan_reuses_the_authoritative_career_tools():
    titan = subagents._SPECIALISTS["titan"]
    assert "career_profile_status" in titan["tools"]
    assert "career_profile_update" in titan["tools"]
    assert "career_profile_fill_field" in titan["tools"]
    assert "OWNER AUTHENTICATION REQUIRED" in titan["prompt"]


def test_confirmed_contact_can_fill_without_exposing_value(profile, monkeypatch):
    profile.update(
        {"contact_information": {"phone": "+234 801 234 5678"}},
        owner_confirmed=True,
    )
    monkeypatch.setattr(career_tools, "get_career_profile", lambda: profile)
    captured = {}

    def fake_fill(value, selector="", label=""):
        captured.update(value=value, selector=selector, label=label)
        return "Filled 'Phone'; postcondition verified by field value read-back."

    monkeypatch.setattr("reyes_agent.tools.browser.browser_fill", fake_fill)
    result = career_tools.career_profile_fill_field(
        "contact_information", label="Phone", subfield="phone"
    )

    assert captured["value"] == "+234 801 234 5678"
    assert "+234 801 234 5678" not in result
    assert "postcondition verified" in result


def test_all_requested_pdf_fields_have_one_authoritative_schema():
    assert len(PROFILE_FIELDS) == len(set(PROFILE_FIELDS))
    assert {
        "full_name", "employment_history", "education", "projects",
        "salary_rate_expectations", "cv_versions", "cover_letter_templates",
        "professional_social_links", "contact_information", "registered_gmail",
    } <= set(PROFILE_FIELDS)
