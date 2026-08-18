# ZENO Project Execution Report

Date: 2026-08-18

Approved contracts can become projects with a dependency graph, bounded task
states, agent-role recommendations and isolated task failure records. A task
cannot be marked complete without both output evidence and a test/postcondition.
QA evaluates named checks with evidence and produces either a failure or
`PROJECT READY FOR OWNER REVIEW`.

Delivery requires passing QA, owner approval and delivery evidence. The engine
records delivery; it does not silently send files. Revision allowance, revision
usage and scope change detection are tracked, with scope creep producing
`SCOPE CHANGE DETECTED` rather than hidden extra work.

The implementation reuses existing agents, missions and project/build tools.
It adds no permanent workers, agent loops or dev servers.

Tests cover dependencies, agent failure, evidence gates, QA failure/success,
delivery gating, revision accounting and scope creep.

Limit: the career engine plans and records the work graph; actual code, website
or document execution remains the responsibility of ZENO's existing approved
Builder/tool runtime.
