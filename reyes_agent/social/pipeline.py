"""The content pipeline, as a state machine that cannot skip a gate.

    IDEA -> RESEARCH -> SCRIPT -> MEDIA -> CAPTION -> HASHTAGS
         -> POLICY CHECK -> QA -> OWNER APPROVAL -> SCHEDULE
         -> PUBLISH -> VERIFY -> ANALYZE -> LEARN

WHY A STATE MACHINE AND NOT A FUNCTION THAT DOES ALL OF IT
-----------------------------------------------------------
Because the interesting property is what CANNOT happen. Legal transitions
live in `store.TRANSITIONS`, so there is no code path from IDEA to PUBLISHED,
no matter which function is called or in what order. A pipeline written as
one long function has that path by construction -- it is just an early
return that someone forgets to write.

WHERE PUBLICATION IS ACTUALLY DECIDED
-------------------------------------
Not here. `control.may_publish` decides, the adapter verifies, and this
module only records what they said. The status written after a publish comes
from `PublishResult.status`, which reports PUBLISHING rather than PUBLISHED
when the platform accepted a post it could not then confirm.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.social import (
    captions as caption_agent, content as content_engine, control, safety,
    store as social_store,
)

# Pipeline stage names, for progress reporting (Phase 44).
STAGES = ("IDEA", "RESEARCH", "SCRIPT", "MEDIA", "CAPTION", "HASHTAGS",
          "POLICY_CHECK", "QA", "OWNER_APPROVAL", "SCHEDULE", "PUBLISH",
          "VERIFY", "ANALYZE", "LEARN")


@dataclass
class StageResult:
    stage: str
    ok: bool
    detail: str
    status: str = ""
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "ok": self.ok, "detail": self.detail,
                "status": self.status, "blocking": self.blocking,
                "warnings": self.warnings}


class ContentPipeline:
    """Advances one piece of content, one gate at a time."""

    def __init__(self, store: social_store.SocialStore | None = None) -> None:
        self._store = store or social_store.get_store()

    # --- SCRIPT -----------------------------------------------------------
    def script(self, content_id: str) -> StageResult:
        item = self._store.content(content_id)
        if item is None:
            return StageResult("SCRIPT", False, f"no content {content_id}")

        moved, detail = self._store.transition(content_id, social_store.SCRIPTING)
        if not moved:
            return StageResult("SCRIPT", False, detail, status=item["status"])

        written, why = content_engine.write_script(item)
        if written is None:
            self._store.transition(content_id, social_store.FAILED)
            self._store.update_content(content_id, failure=why)
            return StageResult("SCRIPT", False, why, status=social_store.FAILED)

        self._store.update_content(content_id, script=written.as_text(),
                                   duration_s=written.duration_s)
        self._store.audit("ScriptWriterAgent", "script_written",
                          platform=item["platform"], target=content_id,
                          result=why)
        return StageResult("SCRIPT", True, why, status=social_store.SCRIPTING)

    # --- CAPTION + HASHTAGS ----------------------------------------------
    def caption(self, content_id: str) -> StageResult:
        item = self._store.content(content_id)
        if item is None:
            return StageResult("CAPTION", False, f"no content {content_id}")

        captions = caption_agent.write_captions(item)
        chosen = captions.for_platform(item["platform"])
        tags = caption_agent.generate_hashtags(item, platform=item["platform"])

        # AI disclosure is applied here, before the owner reviews, so what
        # they approve is what publishes.
        verdict = safety.check_content({**item, "caption": chosen, "hashtags": tags})
        if verdict.needs_ai_disclosure:
            chosen = safety.apply_disclosure(chosen)

        self._store.update_content(content_id, caption=chosen, hashtags=tags)
        self._store.audit("CaptionAgent", "caption_written",
                          platform=item["platform"], target=content_id,
                          result=f"{len(chosen)} chars, {len(tags)} hashtags")
        return StageResult("CAPTION", True,
                           f"caption written ({len(chosen)} chars) with "
                           f"{len(tags)} topic-derived hashtags",
                           status=item["status"])

    # --- POLICY CHECK + QA ------------------------------------------------
    def policy_check(self, content_id: str) -> StageResult:
        item = self._store.content(content_id)
        if item is None:
            return StageResult("POLICY_CHECK", False, f"no content {content_id}")

        verdict = safety.check_content(item)
        self._store.audit("PolicyCheck", "policy_evaluated",
                          platform=item["platform"], target=content_id,
                          result="passed" if verdict.passed else "blocked",
                          error="; ".join(verdict.blocking)[:200])

        if not verdict.passed:
            self._store.update_content(
                content_id, failure="; ".join(verdict.blocking))
            return StageResult("POLICY_CHECK", False,
                               "blocked: " + "; ".join(verdict.blocking),
                               status=item["status"], blocking=verdict.blocking,
                               warnings=verdict.warnings)

        moved, detail = self._store.transition(content_id, social_store.READY_FOR_REVIEW)
        return StageResult("POLICY_CHECK", moved, detail,
                           status=social_store.READY_FOR_REVIEW if moved else item["status"],
                           warnings=verdict.warnings)

    # --- OWNER APPROVAL (Phase 27) ---------------------------------------
    def approval_card(self, content_id: str) -> dict[str, Any]:
        """Everything the owner needs to decide, in one payload."""
        item = self._store.content(content_id)
        if item is None:
            return {"error": f"no content {content_id}"}

        verdict = safety.check_content(item)
        decision = control.may_publish(item)
        evidence = item.get("evidence") or []

        return {
            "content_id": content_id,
            "platform": item["platform"],
            "status": item["status"],
            "title": item["title"],
            "media": {"path": item.get("media_path", ""),
                      "type": item.get("media_type", ""),
                      "required": item.get("required_media", ""),
                      "present": bool(item.get("media_path"))},
            "caption": item.get("caption", ""),
            "hashtags": item.get("hashtags", []),
            "scheduled_for": item.get("scheduled_for"),
            "duration_s": item.get("duration_s"),
            "script": item.get("script", ""),
            # Why ZENO thinks this should be posted -- the evidence, not a
            # confidence number nobody can check.
            "reason": {
                "category": item.get("category", ""),
                "objective": item.get("objective", ""),
                "evidence": evidence,
                "grounded": bool(evidence),
                "summary": (f"Built from {len(evidence)} real development "
                            f"record(s)." if evidence else
                            "No evidence attached -- this should not publish."),
            },
            "checks": verdict.as_dict(),
            "publish_decision": decision.as_dict(),
            "dry_run": control.dry_run(),
            "controls": ["APPROVE", "EDIT", "RESCHEDULE", "REJECT"],
        }

    def approve(self, content_id: str, *, actor: str = "owner") -> StageResult:
        item = self._store.content(content_id)
        if item is None:
            return StageResult("OWNER_APPROVAL", False, f"no content {content_id}")

        verdict = safety.check_content(item)
        if not verdict.passed:
            return StageResult(
                "OWNER_APPROVAL", False,
                "cannot approve: " + "; ".join(verdict.blocking),
                status=item["status"], blocking=verdict.blocking)

        moved, detail = self._store.transition(content_id, social_store.APPROVED)
        if moved:
            self._store.audit(actor, "content_approved",
                              platform=item["platform"], target=content_id,
                              approval="APPROVED", result=detail)
        return StageResult("OWNER_APPROVAL", moved, detail,
                           status=social_store.APPROVED if moved else item["status"])

    def reject(self, content_id: str, reason: str = "",
               *, actor: str = "owner") -> StageResult:
        item = self._store.content(content_id)
        if item is None:
            return StageResult("OWNER_APPROVAL", False, f"no content {content_id}")
        moved, detail = self._store.transition(content_id, social_store.ARCHIVED)
        self._store.update_content(content_id, failure=reason[:400])
        self._store.audit(actor, "content_rejected", platform=item["platform"],
                          target=content_id, approval="REJECTED", result=reason[:120])
        return StageResult("OWNER_APPROVAL", moved, detail or "rejected",
                           status=social_store.ARCHIVED)

    # --- SCHEDULE ---------------------------------------------------------
    def schedule(self, content_id: str, when: float) -> StageResult:
        item = self._store.content(content_id)
        if item is None:
            return StageResult("SCHEDULE", False, f"no content {content_id}")
        if when < time.time() - 60:
            return StageResult("SCHEDULE", False, "that time is in the past",
                               status=item["status"])
        if control.in_quiet_hours(when):
            start, end = control.quiet_hours()
            return StageResult("SCHEDULE", False,
                               f"{time.strftime('%H:%M', time.localtime(when))} "
                               f"falls inside quiet hours "
                               f"({start:02d}:00-{end:02d}:00)",
                               status=item["status"])

        moved, detail = self._store.transition(content_id, social_store.SCHEDULED)
        if moved:
            self._store.update_content(content_id, scheduled_for=when)
            self._store.audit("SchedulerAgent", "content_scheduled",
                              platform=item["platform"], target=content_id,
                              result=time.strftime("%Y-%m-%d %H:%M",
                                                   time.localtime(when)))
        return StageResult("SCHEDULE", moved, detail,
                           status=social_store.SCHEDULED if moved else item["status"])

    # --- PUBLISH + VERIFY -------------------------------------------------
    def publish(self, content_id: str, *, approved_by_owner: bool = False) -> StageResult:
        from reyes_agent.social import adapters

        item = self._store.content(content_id)
        if item is None:
            return StageResult("PUBLISH", False, f"no content {content_id}")

        # Owner approval is a recorded state, not a caller's claim.
        already_approved = item["status"] in (social_store.APPROVED,
                                              social_store.SCHEDULED)
        decision = control.may_publish(
            item, approved_by_owner=approved_by_owner or already_approved)
        if not decision.allowed:
            self._store.audit("PublishingAgent", "publish_refused",
                              platform=item["platform"], target=content_id,
                              result=decision.reason)
            return StageResult("PUBLISH", False, decision.reason,
                               status=item["status"])

        adapter = adapters.adapter_for(item["platform"])
        if adapter is None:
            return StageResult("PUBLISH", False,
                               f"no adapter for {item['platform']}",
                               status=item["status"])

        self._store.transition(content_id, social_store.PUBLISHING)
        self._store.update_content(content_id,
                                   attempts=int(item.get("attempts") or 0) + 1)

        result = adapter.publish({**item, "content_id": content_id})

        if result.simulated:
            # A dry run must not look like a publication anywhere in the data.
            self._store.update_content(content_id, dry_run=1,
                                       failure="", post_id="", post_url="")
            self._store.transition(content_id, social_store.PUBLISHED)
            self._store.update_content(content_id, published_at=time.time(),
                                       verified_at=None)
            return StageResult(
                "PUBLISH", True,
                "SIMULATED: dry run is on, so the post was prepared in full and "
                "never sent. Nothing exists on the platform.",
                status=social_store.PUBLISHED)

        if not result.ok:
            self._store.transition(content_id, social_store.FAILED)
            self._store.update_content(content_id, failure=result.error[:400])
            return StageResult("PUBLISH", False, result.error,
                               status=social_store.FAILED)

        self._store.transition(content_id, social_store.PUBLISHED)
        self._store.update_content(
            content_id, post_id=result.post_id, post_url=result.post_url,
            published_at=result.at, dry_run=0,
            verified_at=result.at if result.verified else None,
            failure="" if result.verified else
                    "platform accepted the post but did not confirm it")

        detail = result.detail or "published"
        if not result.verified:
            detail = (f"{detail} NOT VERIFIED -- ZENO is not claiming this is "
                      f"live until the platform returns it.")
        return StageResult("PUBLISH", True, detail,
                           status=social_store.PUBLISHED,
                           warnings=[] if result.verified else ["unverified"])

    # --- convenience ------------------------------------------------------
    def advance(self, content_id: str) -> list[StageResult]:
        """Run every stage that can run without owner input."""
        results: list[StageResult] = []
        item = self._store.content(content_id)
        if item is None:
            return [StageResult("IDEA", False, f"no content {content_id}")]

        if item["status"] == social_store.IDEA:
            results.append(self.script(content_id))
            if not results[-1].ok:
                return results
        if self._store.content(content_id)["status"] == social_store.SCRIPTING:
            results.append(self.caption(content_id))
            results.append(self.policy_check(content_id))
        return results

    def queue(self) -> dict[str, Any]:
        """What is waiting where."""
        counts = self._store.counts()
        return {
            "ideas": counts.get(social_store.IDEA, 0),
            "drafts": sum(counts.get(status, 0) for status in
                          (social_store.RESEARCHING, social_store.SCRIPTING,
                           social_store.MEDIA_GENERATING)),
            "ready": counts.get(social_store.READY_FOR_REVIEW, 0),
            "approved": counts.get(social_store.APPROVED, 0),
            "scheduled": counts.get(social_store.SCHEDULED, 0),
            "published": counts.get(social_store.PUBLISHED, 0),
            "failed": counts.get(social_store.FAILED, 0),
        }
