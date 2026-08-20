# Codex / Claude coordination

Updated: 2026-08-20

## Claude-owned work detected

Claude's live workspace is `C:\Users\T21SERVICES\Desktop\REYES` on
`feat/zeno-anywhere-v1`. At the start and again before integration it contained
uncommitted changes to `.gitignore` and `presentation/*.json`.

## Codex-owned work

Codex works only in the separate worktree
`C:\Users\T21SERVICES\Desktop\REYES-codex-evolution` on
`codex/zeno-evolution`, based on clean commit `fefc6eb`.

Scope:

- public-target validation and deterministic crawler cleanup;
- thread-safe provider client initialization;
- one reusable, bounded Council executor;
- focused regression tests, benchmarks and evolution documentation.

## Files Codex must avoid

- `.gitignore`
- `presentation/current_facts.json`
- `presentation/current_features.json`
- `presentation/engineering_challenges.json`
- `presentation/learning_portfolio.json`
- `presentation/likely_questions.json`
- `presentation/project_evidence.json`
- `presentation/siwes_profile.json`
- `presentation/visitor_profile.json`
- `presentation/zeno_timeline.json`

## Shared files

None at the time this worktree was created. If Claude later changes
`provider.py`, `council.py`, `kernel.py`, or `research/crawler/*`, integrate by
reviewed cherry-pick/manual merge rather than replacing either version.

## Completed Codex improvements

- closed measured SSRF and streamed-response resource gaps;
- reduced concurrent first-use SDK construction from 32 clients to one;
- reduced ten concurrent Council meetings from 37 provider workers to four;
- preserved normal four-advisor parallelism and added deterministic tests.

## Verification

- complete Python suite: 1,474 passed, 1 optional-backend skip;
- focused live-config voice/design regression: 53 passed, 1 optional skip;
- environment contract: 274 documented variables, 197 code reads, no gaps;
- Python dependency integrity, bytecode compilation and web build tests pass.

The complete run used the owner's ignored `.env` and live ignored MCP registry
without printing, copying or staging either. Test-generated presentation
snapshots were restored in this worktree immediately after the run.

## Integration point

Cherry-pick the final atomic Codex commit only after Claude's current dirty work
is committed. Never force-checkout or clean Claude's workspace. There are no
required manual edits in Claude-owned files.
