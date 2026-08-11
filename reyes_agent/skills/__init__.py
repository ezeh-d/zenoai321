"""ZENO's skills -- workflows it noticed, and only runs once you agree.

    OBSERVED   a sequence repeated. A statistic. Cannot run.
    LEARNED    it cleared the thresholds. ZENO may suggest it. Cannot run.
    APPROVED   you said yes. Now it runs -- through the same permission
               engine as every other action.

`constitution.py` is the part that matters: a skill can never grant itself
privileges, widen permissions, expose ports, disable guardrails, touch
credential or financial policy, or delete audit logs. That is checked when a
skill is stored, when it is approved, and again before every run.

Learning uses `zeno_action_history`, which ZENO already writes. Nothing new
is watched, and action NAMES are learned while resource paths are not.
"""

from __future__ import annotations

# Dependency order: models has no intra-package deps, constitution reads
# duck-typed skills, registry needs both, then learner/executor, then the
# manager facade on top.
from reyes_agent.skills import models, constitution      # no intra-package deps
from reyes_agent.skills import registry                  # needs the two above
from reyes_agent.skills import confidence                 # reads a skill's history
from reyes_agent.skills import versions                   # needs registry
from reyes_agent.skills import executor, learner          # need registry
from reyes_agent.skills import correction                 # needs registry + versions
from reyes_agent.skills import demonstration              # needs registry
from reyes_agent.skills import composer                   # needs registry + capabilities
from reyes_agent.skills import manager                    # needs everything
from reyes_agent.skills.models import APPROVED, LEARNED, OBSERVED, RETIRED, Skill, Step

__all__ = ["Skill", "Step", "OBSERVED", "LEARNED", "APPROVED", "RETIRED",
           "models", "constitution", "registry", "learner", "executor", "manager",
           "composer", "demonstration", "correction", "versions", "confidence",
           "observe", "learn", "suggest", "approve", "run", "status",
           "compose", "watch", "correct", "rollback"]

observe = manager.observe
learn = manager.learn
suggest = manager.suggest
approve = manager.approve
run = manager.run
status = manager.status
compose = composer.compose
watch = demonstration.generalise
correct = correction.correct
rollback = versions.rollback
