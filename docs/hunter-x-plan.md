# HUNTER X research and paper implementation

Owner approved crypto spot, equities and forex on 2026-09-07.
Reuse the ZENO registry, specialist runtime, Event Bus and panel manager.
No real orders, broker credentials, separate server or idle scanner thread.

Sequence: tests first; typed instrument/bar quality validation; deterministic
risk sizing; atomic SQLite paper ledger; chronological next-bar backtesting;
market adapters; research/evaluation metadata; lazy ZENO tools and specialist;
event-driven panel; focused regressions; real public data smoke test; report.

Initial scope is cash-backed long-only paper positions across the three
markets. Forex units represent base-currency spot units, not leveraged broker
lots. No currency conversion is inferred. Historical daily observations never
masquerade as executable quotes. Public data adapters are research-only.

Tests must prove data rejection, cost arithmetic, currency isolation, risk
veto, duplicate idempotency, restart persistence, next-bar signal execution,
kill switch, tool/agent registration and error isolation. Real provider results
are separate from fixture tests. Training and live-readiness remain UNPROVEN
until actual evidence is collected; no fabricated graduation or profitability.
