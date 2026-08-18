"""Owner-verified career data for job and freelance profile assistance.

This is deliberately a data boundary, not an account bot.  ZENO may use the
confirmed facts to draft or fill a profile when a platform permits it, but it
cannot turn model inference into employment history, qualifications, or other
claims about the owner.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from reyes_agent import config
from reyes_agent.memory.privacy import contains_secret


PROFILE_FIELDS = (
    "full_name",
    "professional_title",
    "professional_summary",
    "skills",
    "employment_history",
    "education",
    "certifications",
    "projects",
    "portfolio",
    "languages",
    "availability",
    "preferred_job_types",
    "preferred_industries",
    "remote_on_site_preference",
    "salary_rate_expectations",
    "notice_period",
    "work_authorization",
    "cv_versions",
    "cover_letter_templates",
    "portfolio_links",
    "professional_social_links",
    "location",
    "contact_information",
    "registered_gmail",
)

LIST_FIELDS = frozenset({
    "skills", "employment_history", "education", "certifications", "projects",
    "portfolio", "languages", "preferred_job_types", "preferred_industries",
    "cv_versions", "cover_letter_templates", "portfolio_links",
    "professional_social_links",
})
STRING_FIELDS = frozenset(PROFILE_FIELDS) - LIST_FIELDS - {"contact_information"}
CONTACT_FIELDS = frozenset({"email", "phone", "city", "region", "country", "website"})
SECRET_KEY_MARKERS = (
    "password", "passwd", "secret", "token", "cookie", "credential",
    "security_code", "mfa", "otp", "passkey", "private_key", "recovery_code",
)
MAX_REVISIONS = 50
MAX_PROFILE_BYTES = 256_000
AUTHENTICATION_REQUIRED = "OWNER AUTHENTICATION REQUIRED"

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class CareerProfileError(ValueError):
    """A safe, owner-actionable profile validation failure."""


def _default_db_path() -> Path:
    return config.VAULT_PATH / "07-System" / "career" / "profile.sqlite3"


def _mask_email(value: str) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return "[not configured]" if not text else "[masked]"
    local, domain = text.split("@", 1)
    visible = local[:1] if local else ""
    return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"


def _mask_contact(value: Any) -> Any:
    if not isinstance(value, dict):
        return "[masked]" if value else value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key == "email":
            result[key] = _mask_email(str(item))
        elif key == "phone":
            digits = "".join(ch for ch in str(item) if ch.isdigit())
            result[key] = f"***{digits[-4:]}" if digits else "[masked]"
        elif key in {"city", "region", "country"}:
            result[key] = item
        else:
            result[key] = "[masked]" if item else item
    return result


def _has_secret_key(key: str) -> bool:
    folded = str(key).casefold().replace("-", "_").replace(" ", "_")
    return any(marker in folded for marker in SECRET_KEY_MARKERS)


def _validate_node(value: Any, *, path: str, depth: int = 0) -> Any:
    if depth > 5:
        raise CareerProfileError(f"{path} is nested too deeply.")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) > 8_000:
            raise CareerProfileError(f"{path} is too long.")
        if contains_secret(text):
            raise CareerProfileError(
                f"{path} appears to contain a password, token, or private key. "
                "Credentials must never be saved in the career profile."
            )
        return text
    if isinstance(value, list):
        if len(value) > 200:
            raise CareerProfileError(f"{path} has too many entries (maximum 200).")
        return [_validate_node(item, path=f"{path}[{index}]", depth=depth + 1)
                for index, item in enumerate(value)]
    if isinstance(value, dict):
        if len(value) > 60:
            raise CareerProfileError(f"{path} has too many keys.")
        clean: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key).strip()
            if not key:
                raise CareerProfileError(f"{path} contains an empty key.")
            if _has_secret_key(key):
                raise CareerProfileError(
                    f"{path}.{key} is credential material and cannot be saved."
                )
            clean[key] = _validate_node(item, path=f"{path}.{key}", depth=depth + 1)
        return clean
    raise CareerProfileError(f"{path} has unsupported type {type(value).__name__}.")


class ZenoCareerProfile:
    """One revisioned, owner-confirmed source of truth for career facts."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        registered_gmail: Callable[[], str] | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self._registered_gmail = registered_gmail or (lambda: config.GMAIL_ADDRESS)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS career_profile ("
            "id INTEGER PRIMARY KEY CHECK(id = 1), schema_version INTEGER NOT NULL, "
            "profile_json TEXT NOT NULL, provenance_json TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS career_profile_revisions ("
            "revision INTEGER PRIMARY KEY AUTOINCREMENT, profile_json TEXT NOT NULL, "
            "provenance_json TEXT NOT NULL, changed_fields_json TEXT NOT NULL, "
            "created_at REAL NOT NULL)"
        )
        conn.commit()
        return conn

    @staticmethod
    def _decode(row: tuple[str, str] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if not row:
            return {}, {}
        try:
            profile = json.loads(row[0])
            provenance = json.loads(row[1])
        except (TypeError, json.JSONDecodeError) as exc:
            raise CareerProfileError("The local career profile is corrupt; no data was changed.") from exc
        if not isinstance(profile, dict) or not isinstance(provenance, dict):
            raise CareerProfileError("The local career profile has an invalid format.")
        return profile, provenance

    def _stored(self, conn: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, Any]]:
        row = conn.execute(
            "SELECT profile_json, provenance_json FROM career_profile WHERE id = 1"
        ).fetchone()
        return self._decode(row)

    def raw_profile(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return an internal copy. Credentials can never enter this result."""
        with self._lock:
            with closing(self._connect()) as conn:
                profile, provenance = self._stored(conn)
        configured = str(self._registered_gmail() or "").strip()
        if configured:
            profile["registered_gmail"] = configured
            provenance["registered_gmail"] = "configured_account"
        return deepcopy(profile), deepcopy(provenance)

    def status(self) -> dict[str, Any]:
        profile, provenance = self.raw_profile()
        present = [field for field in PROFILE_FIELDS if field in provenance]
        missing = [field for field in PROFILE_FIELDS if field not in provenance]
        return {
            "schema_version": 1,
            "source_of_truth": "ZenoCareerProfile",
            "owner_verified_fields": [
                field for field in present if provenance.get(field) == "owner_confirmed"
            ],
            "configured_fields": [
                field for field in present if provenance.get(field) == "configured_account"
            ],
            "present_fields": present,
            "missing_fields": missing,
            "completeness_percent": round(100 * len(present) / len(PROFILE_FIELDS), 1),
            "registered_gmail": _mask_email(str(profile.get("registered_gmail", ""))),
            "rule": "Missing facts stay missing until Divine confirms them; ZENO never invents profile claims.",
        }

    def read(self, section: str = "all") -> dict[str, Any]:
        sections = {
            "professional": {
                "full_name", "professional_title", "professional_summary", "skills",
                "employment_history", "education", "certifications", "projects",
                "portfolio", "languages",
            },
            "preferences": {
                "availability", "preferred_job_types", "preferred_industries",
                "remote_on_site_preference", "salary_rate_expectations", "notice_period",
                "work_authorization", "location",
            },
            "assets": {
                "cv_versions", "cover_letter_templates", "portfolio_links",
                "professional_social_links",
            },
            "contact": {"contact_information", "registered_gmail"},
            "all": set(PROFILE_FIELDS),
        }
        requested = str(section or "all").strip().lower()
        if requested not in sections:
            raise CareerProfileError(
                f"Unknown section '{section}'. Use professional, preferences, assets, contact, or all."
            )
        profile, provenance = self.raw_profile()
        result = {field: deepcopy(profile[field]) for field in PROFILE_FIELDS
                  if field in sections[requested] and field in profile}
        if "registered_gmail" in result:
            result["registered_gmail"] = _mask_email(str(result["registered_gmail"]))
        if "contact_information" in result:
            result["contact_information"] = _mask_contact(result["contact_information"])
        return {
            "section": requested,
            "profile": result,
            "provenance": {key: provenance[key] for key in result if key in provenance},
            "missing_fields": [field for field in PROFILE_FIELDS
                               if field in sections[requested] and field not in provenance],
        }

    def _validated_changes(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fields, dict) or not fields:
            raise CareerProfileError("Give at least one owner-confirmed profile field.")
        unknown = sorted(set(fields) - set(PROFILE_FIELDS))
        if unknown:
            raise CareerProfileError(f"Unknown career profile field(s): {', '.join(unknown)}.")
        clean: dict[str, Any] = {}
        configured_gmail = str(self._registered_gmail() or "").strip()
        for field, value in fields.items():
            if field in LIST_FIELDS and not isinstance(value, list):
                raise CareerProfileError(f"{field} must be a list.")
            if field in STRING_FIELDS and not isinstance(value, str):
                raise CareerProfileError(f"{field} must be text.")
            if field == "contact_information":
                if not isinstance(value, dict):
                    raise CareerProfileError("contact_information must be an object.")
                secret_contact = sorted(key for key in value if _has_secret_key(str(key)))
                if secret_contact:
                    raise CareerProfileError(
                        "contact_information contains credential material and cannot be saved."
                    )
                unknown_contact = sorted(set(value) - CONTACT_FIELDS)
                if unknown_contact:
                    raise CareerProfileError(
                        "Unsupported contact field(s): " + ", ".join(unknown_contact) + "."
                    )
            normal = _validate_node(value, path=field)
            if field == "registered_gmail":
                email = str(normal).strip().lower()
                if not _EMAIL.fullmatch(email):
                    raise CareerProfileError("registered_gmail must be a valid email address.")
                if configured_gmail and email != configured_gmail.lower():
                    raise CareerProfileError(
                        "That address is not ZENO's configured registered Gmail account."
                    )
                normal = email
            clean[field] = normal
        encoded = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_PROFILE_BYTES:
            raise CareerProfileError("That update is too large for one career profile change.")
        return clean

    def update(self, fields: dict[str, Any], *, owner_confirmed: bool) -> dict[str, Any]:
        if owner_confirmed is not True:
            raise CareerProfileError(
                "Profile facts must be explicitly confirmed by Divine before they are saved."
            )
        changes = self._validated_changes(fields)
        now = time.time()
        with self._lock:
            with closing(self._connect()) as conn, conn:
                current, provenance = self._stored(conn)
                current.update(deepcopy(changes))
                provenance.update({field: "owner_confirmed" for field in changes})
                profile_json = json.dumps(current, ensure_ascii=False, sort_keys=True)
                provenance_json = json.dumps(provenance, ensure_ascii=False, sort_keys=True)
                if len(profile_json.encode("utf-8")) > MAX_PROFILE_BYTES:
                    raise CareerProfileError("The resulting career profile is too large.")
                conn.execute(
                    "INSERT INTO career_profile (id, schema_version, profile_json, provenance_json, updated_at) "
                    "VALUES (1, 1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                    "schema_version = excluded.schema_version, profile_json = excluded.profile_json, "
                    "provenance_json = excluded.provenance_json, updated_at = excluded.updated_at",
                    (profile_json, provenance_json, now),
                )
                conn.execute(
                    "INSERT INTO career_profile_revisions "
                    "(profile_json, provenance_json, changed_fields_json, created_at) VALUES (?, ?, ?, ?)",
                    (profile_json, provenance_json, json.dumps(sorted(changes)), now),
                )
                conn.execute(
                    "DELETE FROM career_profile_revisions WHERE revision NOT IN "
                    "(SELECT revision FROM career_profile_revisions ORDER BY revision DESC LIMIT ?)",
                    (MAX_REVISIONS,),
                )
        result = self.status()
        result["updated_fields"] = sorted(changes)
        return result

    def revision_count(self) -> int:
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT COUNT(*) FROM career_profile_revisions").fetchone()
        return int(row[0] if row else 0)


_PROFILE: ZenoCareerProfile | None = None
_PROFILE_LOCK = threading.Lock()


def get_career_profile() -> ZenoCareerProfile:
    global _PROFILE
    with _PROFILE_LOCK:
        if _PROFILE is None:
            _PROFILE = ZenoCareerProfile()
        return _PROFILE


__all__ = [
    "AUTHENTICATION_REQUIRED", "CareerProfileError", "PROFILE_FIELDS",
    "ZenoCareerProfile", "get_career_profile",
]
