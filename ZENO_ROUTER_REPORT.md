# ZENO — Capability Router

## The problem, measured

`tool_definitions(groups=enabled_groups)` returned **core + enabled groups**, and
core alone was **105 schemas** — sent on every turn regardless of what was
asked. The repository had already measured the cost (`tools/__init__.py`):
**~5.4 s at 93 schemas versus ~1.5 s at 5.**

"What time is it?" took **10.05 s**. Most of that was the model reading a
catalogue it was never going to use.

## What was built

`reyes_agent/routing/capability.py` — 21 capability groups mapped to real
registered tool names, a deterministic classifier, per-capability budgets,
short-lived follow-up context, controlled expansion and telemetry.

Wired at the single point in `agent.py` where schemas are chosen. It
**narrows**; it never blocks. `enable_tools` still widens mid-turn, so a
misroute costs one round, not a capability.

## Why the classifier is not a model call

Solving schema overload by adding an LLM call to every request trades one
latency source for another. Classification is word-boundary regex plus recent
conversational state. **Measured: under 15 ms**, asserted by a test.

## The asymmetry that shaped the design

Missing a tool costs one extra round. Exposing a sharp tool that was never
wanted cannot be undone. So the two failure modes are not weighted equally:

- Low confidence expands to a **wider set, never everything**
- Destructive capabilities require an **imperative, not a mention**

This is why the patterns match grammar rather than keywords:

| request | `delete_file` exposed? |
|---|---|
| "Tell me what deleting a folder means" | **No** |
| "delete the old report file" | **Yes** |
| "How does PayPal work?" | no financial tools at all |

## Routing results

| request | capability | tools exposed |
|---|---|---:|
| Hello ZENO, how are you? | conversation | **2** |
| What time is it? | utility | 12 |
| Open Chrome | browser | 12 |
| Search YouTube for football | browser | 12 |
| Remember my colour is blue | memory | 16 |
| What colour did I tell you? | memory | 16 |
| Look at my screen | vision | 8 |
| Ask all my agents | council | 5 |
| Fix this Python traceback | coding | 9 |
| Send a message on Slack | communication | 6 |
| delete the old report file | files_destructive | 10 |

Against **226 registered / 105 previously sent every turn**.

## Follow-up context

"Search for it" after "Open Chrome" inherits **browser** rather than being
classified alone as a web search. Context lives 120 s and expires — an
unrelated question later is judged on its own.

## Telemetry

Every route records request id, capabilities, confidence, tools exposed vs
registered, router latency and whether it expanded. `Route.explain()` answers
"why did you choose that tool?" from routing facts — not hidden reasoning.

## Tests

**36 router tests**, including budget ceilings, misrouting refusals,
follow-up inheritance, context expiry, and a guard that nothing ever
approaches the old payload.

One test I wrote was wrong and the code was right: "do that again" is also a
workflow phrase, so it sets fresh context instead of inheriting. Corrected the
test, not the router.

## Remaining

The `files` capability still exposes 9 tools for "tell me what deleting means"
— read-only ones, but a conversational question arguably needs none. Tightening
that risks under-routing genuine file work; left as-is deliberately.
